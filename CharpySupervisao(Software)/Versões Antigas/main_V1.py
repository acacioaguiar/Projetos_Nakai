import sys
import struct

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QGridLayout, QLabel,
    QPushButton, QDoubleSpinBox, QSpinBox, QGroupBox,
    QFormLayout
)
from pymodbus.client import ModbusTcpClient


# Configuração confirmada no teste de comunicação.
IP_CLP = "10.0.0.20"
PORTA_MODBUS = 502
UNIT_ID = 1
INTERVALO_LEITURA_MS = 200


def words_para_float_invertido(word1, word2):
    """Interpreta REAL de 32 bits com a palavra baixa antes da alta."""
    return struct.unpack(
        ">f", struct.pack(">HH", word2, word1)
    )[0]


class LeitorModbus(QThread):
    """Thread de leitura. Não possui nenhuma chamada de escrita Modbus."""

    dados_recebidos = Signal(float, float, float)
    estado_conexao = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parar = False
        self.client = None

    def solicitar_parada(self):
        self._parar = True

    def run(self):
        self.client = ModbusTcpClient(
            host=IP_CLP,
            port=PORTA_MODBUS,
            timeout=2
        )

        try:
            while not self._parar:
                if not self.client.connected:
                    if not self.client.connect():
                        self.estado_conexao.emit(
                            f"SEM CONEXÃO — não foi possível conectar a {IP_CLP}:{PORTA_MODBUS}",
                            False
                        )
                        self.msleep(INTERVALO_LEITURA_MS)
                        continue

                    self.estado_conexao.emit(
                        f"CONECTADO — {IP_CLP}:{PORTA_MODBUS} (somente leitura)",
                        True
                    )

                # Lê %MW2 até %MW5, que no projeto correspondem
                # aos words que compõem %MF2 e %MF4.
                    resposta = self.client.read_holding_registers(
                    address=2,
                    count=8,
                    slave=UNIT_ID
                    )

                if resposta.isError():
                    self.estado_conexao.emit(
                        f"ERRO MODBUS — {resposta}",
                        False
                    )
                else:
                    regs = resposta.registers
                    angulo = words_para_float_invertido(regs[0], regs[1])
                    pico = words_para_float_invertido(regs[2], regs[3])
                    energia = words_para_float_invertido(regs[6], regs[7])

                # Rejeita valores inválidos antes de atualizar a interface.
                import math

                if all(math.isfinite(v) for v in (angulo, pico, energia)):
                    self.dados_recebidos.emit(angulo, pico, energia)
                    self.estado_conexao.emit(
                        f"CONECTADO — leitura atualizada de {IP_CLP}:{PORTA_MODBUS}",
                        True
                    )
                else:
                    self.estado_conexao.emit(
                        "ERRO — o CLP retornou um valor inválido",
                        False
                    )

                self.msleep(INTERVALO_LEITURA_MS)

        except Exception as erro:
            self.estado_conexao.emit(
                f"ERRO DE COMUNICAÇÃO — {erro}",
                False
            )
        finally:
            if self.client is not None:
                self.client.close()
            self.estado_conexao.emit("DESCONECTADO", False)


class CharpyApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Charpy Supervisão")
        self.resize(1050, 700)

        self.angulo = None
        self.pico_angulo = None
        self.energia_absorvida = None

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

        energia_box = QGroupBox("Parâmetros do ensaio")
        energia_form = QFormLayout(energia_box)

        self.energia_nominal = QDoubleSpinBox()
        self.energia_nominal.setRange(1, 1000)
        self.energia_nominal.setValue(300)
        self.energia_nominal.setSuffix(" J")
        energia_form.addRow("Energia nominal:", self.energia_nominal)
        layout.addWidget(energia_box)

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
            "Energia absorvida", "Indisponível"
        )
        indicadores.addWidget(caixa, 1, 0, 1, 2)

        layout.addLayout(indicadores)

        comandos = QGroupBox("Comandos — desabilitados durante a integração de leitura")
        botoes = QGridLayout(comandos)

        self.btn_subir = QPushButton("SUBIR")
        self.btn_descer = QPushButton("DESCER")
        self.btn_zerar = QPushButton("SOLICITAR REFERÊNCIA")
        self.btn_impacto = QPushButton("IMPACTO")

        botoes.addWidget(self.btn_subir, 0, 0)
        botoes.addWidget(self.btn_descer, 0, 1)
        botoes.addWidget(self.btn_zerar, 1, 0)
        botoes.addWidget(self.btn_impacto, 1, 1)
        layout.addWidget(comandos)

        self.btn_subir.setEnabled(False)
        self.btn_descer.setEnabled(False)
        self.btn_impacto.setEnabled(False)
        self.btn_zerar.setEnabled(False)

        sensores = QGroupBox("Estado dos sensores e permissões")
        sensores_layout = QGridLayout(sensores)
        self.indicadores_estado = {}

        nomes = [
            "Porta fechada",
            "Sensor inferior",
            "Sensor superior",
            "Referência válida",
            "Máquina pronta",
            "Falha do CLP",
        ]

        for i, nome in enumerate(nomes):
            label = QLabel(f"{nome}: NÃO MAPEADO")
            sensores_layout.addWidget(label, i // 2, i % 2)
            self.indicadores_estado[nome] = label

        layout.addWidget(sensores)
        layout.addStretch()

        return pagina

    def criar_tela_atrito(self):
        pagina = QWidget()
        layout = QVBoxLayout(pagina)

        titulo = QLabel("ENSAIO DE PERDAS POR ATRITO")
        titulo.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(titulo)

        formulario = QFormLayout()

        self.oscilacoes = QSpinBox()
        self.oscilacoes.setRange(1, 1000)
        self.oscilacoes.setValue(5)

        self.angulo_inicial = QDoubleSpinBox()
        self.angulo_inicial.setRange(-180, 180)
        self.angulo_inicial.setDecimals(2)
        self.angulo_inicial.setValue(150)

        self.angulo_final = QDoubleSpinBox()
        self.angulo_final.setRange(-180, 180)
        self.angulo_final.setDecimals(2)
        self.angulo_final.setValue(140)

        formulario.addRow("Número de oscilações:", self.oscilacoes)
        formulario.addRow("Ângulo inicial (°):", self.angulo_inicial)
        formulario.addRow("Ângulo final (°):", self.angulo_final)
        layout.addLayout(formulario)

        self.resultado_atrito = QLabel(
            "Informe os dados e calcule para visualizar o resultado."
        )
        self.resultado_atrito.setWordWrap(True)
        layout.addWidget(self.resultado_atrito)

        calcular = QPushButton("CALCULAR")
        calcular.clicked.connect(self.calcular_atrito)
        layout.addWidget(calcular)

        nota = QLabel(
            "Prévia de software: o cálculo apresentado é ilustrativo. "
            "A fórmula definitiva depende do método de ensaio, "
            "das unidades e do critério normativo aplicável."
        )
        nota.setWordWrap(True)
        layout.addWidget(nota)
        layout.addStretch()
        return pagina

    def receber_dados(self, angulo, pico, energia):
        self.angulo = angulo
        self.pico_angulo = pico
        self.energia_absorvida = energia
        self.atualizar_tela()

    def atualizar_status(self, mensagem, conectado):
        self.status.setText(mensagem)
        if conectado:
            self.status.setStyleSheet(
                "background: #d9f2d9; padding: 10px; font-weight: bold;"
            )
        else:
            self.status.setStyleSheet(
                "background: #f5d6d6; padding: 10px; font-weight: bold;"
            )

    def atualizar_tela(self):
        if self.angulo is not None:
            self.angulo_label.setText(f"{self.angulo:.2f}°")
        else:
            self.angulo_label.setText("Aguardando CLP...")

        if self.pico_angulo is not None:
            self.pico_label.setText(f"{self.pico_angulo:.2f}°")
        else:
            self.pico_label.setText("Aguardando CLP...")

        if self.energia_absorvida is not None:
            self.energia_label.setText(
                f"{self.energia_absorvida:.2f} J"
            )
        else:
            self.energia_label.setText("Aguardando CLP...")

    def calcular_atrito(self):
        n = self.oscilacoes.value()
        inicial = abs(self.angulo_inicial.value())
        final = abs(self.angulo_final.value())

        if inicial <= 0 or final > inicial:
            self.resultado_atrito.setText(
                "Verifique os ângulos. Para esta prévia, "
                "o ângulo final deve ser menor que o inicial."
            )
            return

        import math
        perda_relativa = 1 - (
            math.sin(math.radians(final))
            / math.sin(math.radians(inicial))
        ) ** 2

        self.resultado_atrito.setText(
            f"Oscilações: {n}\n"
            f"Redução relativa estimada: {100 * perda_relativa:.2f}%\n\n"
            "Resultado ilustrativo. Ainda não é um cálculo "
            "normativo nem uma medição validada da máquina."
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
