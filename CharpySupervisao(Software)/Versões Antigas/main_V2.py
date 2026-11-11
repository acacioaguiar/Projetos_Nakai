import sys
import struct
import math

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout
)
from pymodbus.client import ModbusTcpClient


# Configuração confirmada nos testes de comunicação.
IP_CLP = "10.0.0.20"
PORTA_MODBUS = 502
UNIT_ID = 1
INTERVALO_LEITURA_MS = 200

# ATENÇÃO:
# Os endereços dos registradores REAL seguem o teste já realizado:
# address=2 -> %MF2 e %MF4.
# Pela mesma convenção, %MF8 deve começar no registrador Modbus 8.
# O mapeamento de %M0...%M13 como coils (address=0...13) precisa
# ser confirmado no M221 antes de confiar nos estados exibidos.


def words_para_float_invertido(word1, word2):
    """Interpreta REAL de 32 bits com a palavra baixa antes da alta."""
    return struct.unpack(">f", struct.pack(">HH", word2, word1))[0]


class LeitorModbus(QThread):
    """Leitura Modbus apenas; não executa nenhuma escrita no CLP."""

    dados_recebidos = Signal(float, float, float, float, list)
    estado_conexao = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parar = False
        self.client = None

    def solicitar_parada(self):
        self._parar = True

    def run(self):
        self.client = ModbusTcpClient(
            host=IP_CLP, port=PORTA_MODBUS, timeout=2
        )
        try:
            while not self._parar:
                if not self.client.connected and not self.client.connect():
                    self.estado_conexao.emit(
                        f"SEM CONEXÃO — não foi possível conectar a {IP_CLP}:{PORTA_MODBUS}",
                        False
                    )
                    self.msleep(INTERVALO_LEITURA_MS)
                    continue

                # %MF2 ocupa %MW2-%MW3; %MF4 ocupa %MW4-%MW5;
                # %MF8 ocupa %MW8-%MW9. Lemos %MW2 até %MW9.
                regs_resp = self.client.read_holding_registers(
                    address=2, count=8, slave=UNIT_ID
                )

                if regs_resp.isError():
                    self.estado_conexao.emit(
                        f"SEM COMUNICAÇÃO — falha na leitura Modbus: {regs_resp}", False
                    )
                    self.client.close()
                    self.msleep(INTERVALO_LEITURA_MS)
                    continue

                regs = regs_resp.registers
                angulo = words_para_float_invertido(regs[0], regs[1])
                pico = words_para_float_invertido(regs[2], regs[3])
                energia = words_para_float_invertido(regs[6], regs[7])

                # %MF120: perda por atrito calculada pelo Ladder.
                perda_resp = self.client.read_holding_registers(
                    address=120, count=2, slave=UNIT_ID
                )
                if perda_resp.isError():
                    perda_atrito = float("nan")
                else:
                    perda_atrito = words_para_float_invertido(
                        perda_resp.registers[0], perda_resp.registers[1]
                    )

                # Leitura tentativa dos bits internos %M0...%M13.
                # Confirmar o offset no mapa Modbus do M221.
                bits_resp = self.client.read_coils(
                    address=0, count=14, slave=UNIT_ID
                )
                if bits_resp.isError():
                    bits = [None] * 14
                    msg_bits = " | bits %M0-%M13 indisponíveis"
                else:
                    bits = list(bits_resp.bits[:14])
                    if len(bits) < 14:
                        bits += [None] * (14 - len(bits))
                    msg_bits = " | leitura dos bits recebida (offset a validar)"

                valores = (angulo, pico, energia)
                if not all(math.isfinite(v) for v in valores):
                    self.estado_conexao.emit(
                        "DADO INVÁLIDO recebido do CLP", False
                    )
                else:
                    self.dados_recebidos.emit(angulo, pico, energia, perda_atrito, bits)
                    self.estado_conexao.emit(
                        f"CONECTADO — leitura atualizada de {IP_CLP}:{PORTA_MODBUS} "
                        f"(somente leitura){msg_bits}",
                        True
                    )

                self.msleep(INTERVALO_LEITURA_MS)

        except Exception as erro:
            self.estado_conexao.emit(f"ERRO DE COMUNICAÇÃO — {erro}", False)
        finally:
            if self.client is not None:
                self.client.close()
            self.estado_conexao.emit("DESCONECTADO", False)


class CharpyApp(QMainWindow):
    # Descrições baseadas nas variáveis nomeadas no projeto Ladder.
    NOMES_MEMORIAS = {
        0: "Engrenagem",
        1: "Motor subir",
        2: "Motor descer",
        3: "Liberar catraca",
        4: "Auxiliar de impacto",
        5: "Ensaio de perdas por atrito",
        6: "Contagem das perdas",
        7: "Auxiliar de subida no ensaio de perdas",
        8: "M8 — função não identificada",
        9: "M9 — função não identificada",
        10: "Falha de porta",
        11: "Falha de subida",
        12: "Falha de descida",
        13: "Falha do motor",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Charpy Supervisão")
        self.resize(1100, 760)

        self.angulo = None
        self.pico_angulo = None
        self.energia_absorvida = None
        self.perda_atrito = None
        self.bits_memoria = [None] * 14

        abas = QTabWidget()
        abas.addTab(self.criar_tela_principal(), "Controle")
        abas.addTab(self.criar_tela_atrito(), "Perdas por atrito")
        self.setCentralWidget(abas)

        self.leitor = LeitorModbus(self)
        self.leitor.dados_recebidos.connect(self.receber_dados)
        self.leitor.estado_conexao.connect(self.atualizar_status)
        self.leitor.start()
        self.atualizar_tela()

    def criar_indicador(self, titulo, valor):
        caixa = QGroupBox(titulo)
        layout = QVBoxLayout(caixa)
        indicador = QLabel(valor)
        indicador.setAlignment(Qt.AlignmentFlag.AlignCenter)
        indicador.setStyleSheet(
            "font-size: 25px; font-weight: bold; padding: 12px;"
        )
        layout.addWidget(indicador)
        return caixa, indicador

    def criar_tela_principal(self):
        pagina = QWidget()
        layout = QVBoxLayout(pagina)

        cabecalho = QLabel("CHARPY — CONTROLE E SUPERVISÃO")
        cabecalho.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(cabecalho)

        self.status = QLabel("INICIANDO COMUNICAÇÃO COM O CLP...")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "background: #e6e6e6; padding: 10px; font-weight: bold;"
        )
        layout.addWidget(self.status)

        parametros = QGroupBox("Parâmetros do ensaio")
        formulario = QFormLayout(parametros)
        self.energia_nominal = QDoubleSpinBox()
        self.energia_nominal.setRange(1, 1000)
        self.energia_nominal.setValue(300)
        self.energia_nominal.setSuffix(" J")
        self.energia_nominal.setToolTip(
            "Informativo nesta versão: o valor não é escrito no CLP "
            "e não altera o cálculo executado pela Ladder."
        )
        formulario.addRow("Energia nominal configurada (informativa):",
                          self.energia_nominal)
        layout.addWidget(parametros)

        indicadores = QGridLayout()
        caixa, self.angulo_label = self.criar_indicador(
            "Ângulo atual (%MF2)", "-- °"
        )
        indicadores.addWidget(caixa, 0, 0)
        caixa, self.pico_label = self.criar_indicador(
            "Pico de ângulo (%MF4)", "-- °"
        )
        indicadores.addWidget(caixa, 0, 1)
        caixa, self.energia_label = self.criar_indicador(
            "Energia absorvida calculada pelo CLP (%MF8)", "-- J"
        )
        indicadores.addWidget(caixa, 1, 0, 1, 2)
        layout.addLayout(indicadores)

        comandos = QGroupBox(
            "Comandos — aguardando confirmação da escrita Modbus"
        )
        botoes = QGridLayout(comandos)
        self.btn_subir = QPushButton("SUBIR")
        self.btn_descer = QPushButton("DESCER")
        self.btn_zerar = QPushButton("SOLICITAR REFERÊNCIA")
        self.btn_impacto = QPushButton("IMPACTO")
        botoes.addWidget(self.btn_subir, 0, 0)
        botoes.addWidget(self.btn_descer, 0, 1)
        botoes.addWidget(self.btn_zerar, 1, 0)
        botoes.addWidget(self.btn_impacto, 1, 1)
        for botao in (self.btn_subir, self.btn_descer,
                      self.btn_zerar, self.btn_impacto):
            botao.setEnabled(False)
        layout.addWidget(comandos)

        estados = QGroupBox("Memórias internas do CLP — %M0 a %M13")
        estados_layout = QGridLayout(estados)
        self.indicadores_memoria = {}
        for i in range(14):
            label = QLabel(f"%M{i} — {self.NOMES_MEMORIAS[i]}: NÃO MAPEADO")
            label.setWordWrap(True)
            label.setStyleSheet("padding: 4px;")
            estados_layout.addWidget(label, i // 2, i % 2)
            self.indicadores_memoria[i] = label
        layout.addWidget(estados)
        aviso = QLabel(
            "Os botões permanecem desabilitados até confirmar o mapeamento e a escrita "
            "Modbus. O teste anterior recebeu resposta de escrita, mas a leitura retornou "
            "False; portanto ainda não é seguro ligar os botões a comandos do CLP. "
            "A leitura de sensores/estados também depende de confirmar o mapa de coils."
        )
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        layout.addStretch()
        return pagina

    def criar_tela_atrito(self):
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        titulo = QLabel("ENSAIO DE PERDAS POR ATRITO")
        titulo.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(titulo)

        formulario = QFormLayout()
        # Somente leitura: os valores serão mostrados quando os endereços
        # correspondentes forem identificados no Ladder/Modbus.
        self.oscilacoes_label = QLabel("Não mapeado no Modbus")
        self.angulo_inicial_label = QLabel("Não mapeado no Modbus")
        self.angulo_final_label = QLabel("Não mapeado no Modbus")
        self.perda_atrito_label = QLabel("-- J")
        formulario.addRow("Número de oscilações:", self.oscilacoes_label)
        formulario.addRow("Ângulo inicial (°):", self.angulo_inicial_label)
        formulario.addRow("Ângulo final (°):", self.angulo_final_label)
        formulario.addRow("Energia perdida por atrito (%MF120):", self.perda_atrito_label)
        layout.addLayout(formulario)

        nota = QLabel(
            "Os campos são somente para visualização. A energia perdida é lida de %MF120. "
            "Número de oscilações e ângulos inicial/final ainda precisam ser associados "
            "a endereços confirmados no Ladder para aparecerem aqui."
        )
        nota.setWordWrap(True)
        layout.addWidget(nota)
        layout.addStretch()
        return pagina

    def receber_dados(self, angulo, pico, energia, perda_atrito, bits):
        self.angulo = angulo
        self.pico_angulo = pico
        self.energia_absorvida = energia
        self.perda_atrito = perda_atrito if math.isfinite(perda_atrito) else None
        self.bits_memoria = bits
        self.atualizar_tela()

    def atualizar_status(self, mensagem, conectado):
        self.status.setText(mensagem)
        if not conectado and hasattr(self, "angulo_label"):
            self.angulo = None
            self.pico_angulo = None
            self.energia_absorvida = None
            self.perda_atrito = None
            self.atualizar_tela()
        if conectado:
            self.status.setStyleSheet(
                "background: #d9f2d9; padding: 10px; font-weight: bold;"
            )
        else:
            self.status.setStyleSheet(
                "background: #f5d6d6; padding: 10px; font-weight: bold;"
            )

    def atualizar_tela(self):
        self.angulo_label.setText(
            f"{self.angulo:.2f}°" if self.angulo is not None else "-- °"
        )
        self.pico_label.setText(
            f"{self.pico_angulo:.2f}°"
            if self.pico_angulo is not None else "-- °"
        )
        self.energia_label.setText(
            f"{self.energia_absorvida:.2f} J"
            if self.energia_absorvida is not None else "-- J"
        )

        self.perda_atrito_label.setText(
            f"{self.perda_atrito:.2f} J" if self.perda_atrito is not None else "-- J"
        )

        for i, bit in enumerate(self.bits_memoria):
            if bit is None:
                estado = "NÃO LIDO — CONFIRMAR MAPA"
            else:
                estado = "ATIVA (1)" if bit else "INATIVA (0)"
            self.indicadores_memoria[i].setText(
                f"%M{i} — {self.NOMES_MEMORIAS[i]}: {estado}"
            )

    def closeEvent(self, event):
        if hasattr(self, "leitor") and self.leitor.isRunning():
            self.leitor.solicitar_parada()
            self.leitor.wait(3000)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    janela = CharpyApp()
    janela.show()
    sys.exit(app.exec())
