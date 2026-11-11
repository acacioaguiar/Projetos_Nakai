import sys
import struct
import math

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout, QMessageBox, QHBoxLayout, QDialog
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

    dados_recebidos = Signal(float, float, float, float, float, list)
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
                # %MF106: ângulo final do ensaio de perdas por atrito.
                angulo_final_resp = self.client.read_holding_registers(
                    address=106, count=2, slave=UNIT_ID
                )
                if perda_resp.isError():
                    perda_atrito = float("nan")
                else:
                    perda_atrito = words_para_float_invertido(
                        perda_resp.registers[0], perda_resp.registers[1]
                    )

                if angulo_final_resp.isError():
                    angulo_final = float("nan")
                else:
                    angulo_final = words_para_float_invertido(
                        angulo_final_resp.registers[0], angulo_final_resp.registers[1]
                    )

                # Leitura das memórias %M0...%M17 (coils Modbus 0...17).
                # O mapeamento de coils do M221 deve ser confirmado no CLP.
                bits_resp = self.client.read_coils(
                    address=0, count=18, slave=UNIT_ID
                )
                if bits_resp.isError():
                    bits = [None] * 18
                    msg_bits = " | bits %M0-%M17 indisponíveis"
                else:
                    bits = list(bits_resp.bits[:18])
                    if len(bits) < 18:
                        bits += [None] * (18 - len(bits))
                    msg_bits = " | estados %M0-%M17 lidos (offset Modbus a validar)"

                valores = (angulo, pico, energia)
                if not all(math.isfinite(v) for v in valores):
                    self.estado_conexao.emit(
                        "DADO INVÁLIDO recebido do CLP", False
                    )
                else:
                    self.dados_recebidos.emit(angulo, pico, energia, perda_atrito, angulo_final, bits)
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
        8: "Solicitação de alternância da esteira (pulso)",
        9: "Estado lógico da esteira",
        10: "Falha de porta",
        11: "Falha de subida",
        12: "Falha de descida",
        13: "Falha do motor",
        14: "Reservada / livre",
        15: "Sensor da porta (espelho Ladder)",
        16: "Sensor de baixo (espelho Ladder)",
        17: "Sensor de cima (espelho Ladder)",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Charpy Supervisão")
        self.resize(1100, 760)

        self.angulo = None
        self.pico_angulo = None
        self.energia_absorvida = None
        self.perda_atrito = None
        self.angulo_final_atrito = None
        self.bits_memoria = [None] * 18
        self.conectado = False
        self.comandos_pendentes = set()
        self.solicitacao_atrito_pendente = False
        self.ensaio_atrito_ativo = False

        self.abas = QTabWidget()
        self.abas.addTab(self.criar_tela_principal(), "Controle")
        self.abas.addTab(self.criar_tela_atrito(), "Perdas por atrito")
        pagina_monitoramento = QWidget()
        layout_monitoramento = QVBoxLayout(pagina_monitoramento)
        mensagem_monitoramento = QLabel(
            "O monitoramento técnico abre em uma janela independente para você "
            "poder posicioná-la ao lado da tela de controle."
        )
        mensagem_monitoramento.setWordWrap(True)
        layout_monitoramento.addWidget(mensagem_monitoramento)
        layout_monitoramento.addStretch()
        self.abas.addTab(pagina_monitoramento, "Monitoramento ↗")
        self._ultima_aba = 0
        self.abas.currentChanged.connect(self.ao_mudar_aba)
        self.setCentralWidget(self.abas)

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
            "Defina a capacidade nominal do pêndulo e clique em Enviar ao CLP. "
            "O valor será escrito em %MF6."
        )
        formulario.addRow("Energia nominal:", self.energia_nominal)
        linha_energia = QHBoxLayout()
        self.btn_enviar_energia = QPushButton("ENVIAR ENERGIA NOMINAL AO CLP")
        self.btn_enviar_energia.setEnabled(False)
        self.btn_enviar_energia.setStyleSheet("padding: 10px; font-weight: bold; background: #d9eaf7;")
        self.btn_enviar_energia.clicked.connect(self.enviar_energia_nominal)
        linha_energia.addWidget(self.btn_enviar_energia)
        formulario.addRow("", linha_energia)
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
        self.btn_zerar = QPushButton("ZERAR REFERÊNCIA")
        self.btn_impacto = QPushButton("EXECUTAR IMPACTO")
        botoes.addWidget(self.btn_subir, 0, 0)
        botoes.addWidget(self.btn_descer, 0, 1)
        botoes.addWidget(self.btn_zerar, 1, 0)
        botoes.addWidget(self.btn_impacto, 1, 1)
        self.btn_esteira = QPushButton("ESTEIRA — AGUARDANDO LEITURA")
        self.btn_esteira.setMinimumHeight(42)
        self.btn_esteira.setEnabled(False)
        botoes.addWidget(self.btn_esteira, 2, 0, 1, 2)
        for botao in (self.btn_subir, self.btn_descer,
                      self.btn_zerar, self.btn_impacto):
            botao.setEnabled(False)
        self.btn_subir.clicked.connect(lambda: self.enviar_comando(101, "Subir"))
        self.btn_descer.clicked.connect(lambda: self.enviar_comando(102, "Descer"))
        self.btn_zerar.clicked.connect(lambda: self.enviar_comando(100, "Zerar referência"))
        self.btn_impacto.clicked.connect(lambda: self.enviar_comando(103, "Impacto", confirmar=True))
        self.btn_esteira.clicked.connect(lambda: self.enviar_comando(8, "Alternar esteira"))
        self.btn_subir.setStyleSheet("padding: 12px; font-weight: bold; background: #d9ead3;")
        self.btn_descer.setStyleSheet("padding: 12px; font-weight: bold; background: #fce5cd;")
        self.btn_zerar.setStyleSheet("padding: 12px; font-weight: bold;")
        self.btn_impacto.setStyleSheet("padding: 12px; font-weight: bold; background: #f4cccc;")
        layout.addWidget(comandos)

        # Janela independente de monitoramento, aberta pela aba superior.
        self.indicadores_memoria = {}
        self.janela_monitoramento = self.criar_janela_monitoramento()

        aviso = QLabel(
            "Os comandos enviam solicitações ao CLP. Antes de qualquer movimento, "
            "o Ladder deve validar permissões e intertravamentos. O monitoramento "
            "detalhado de comandos, falhas e sensores está disponível em uma janela separada."
        )
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        layout.addStretch()
        return pagina

    def criar_janela_monitoramento(self):
        janela = QDialog(self)
        janela.setWindowTitle("Charpy Supervisão — Monitoramento do CLP")
        janela.setModal(False)
        janela.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        janela.resize(760, 500)
        layout = QVBoxLayout(janela)
        titulo = QLabel("MONITORAMENTO DO CLP")
        titulo.setStyleSheet("font-size: 18px; font-weight: bold; padding: 4px;")
        layout.addWidget(titulo)

        def grupo_memorias(titulo_grupo, indices, colunas=2):
            grupo = QGroupBox(titulo_grupo)
            grade = QGridLayout(grupo)
            for pos, i in enumerate(indices):
                label = QLabel(f"%M{i} — {self.NOMES_MEMORIAS[i]}: NÃO LIDO  ●")
                label.setWordWrap(True)
                label.setStyleSheet("padding: 5px;")
                grade.addWidget(label, pos // colunas, pos % colunas)
                self.indicadores_memoria[i] = label
            return grupo

        # Ordem solicitada: comandos, sensores e falhas. M14 permanece livre.
        layout.addWidget(grupo_memorias("Comando", [0, 1, 2, 3, 8, 9]))
        layout.addWidget(grupo_memorias("Sensores", [15, 16, 17]))
        layout.addWidget(grupo_memorias("Falhas", [10, 11, 12, 13]))
        nota = QLabel(
            "%M8 é o pulso de solicitação para alternar a esteira; %M9 mantém o estado lógico. "
            "%M15 = sensor da porta; %M16 = sensor de baixo; %M17 = sensor de cima. "
            "%M14 permanece reservado. Confirme o mapeamento Modbus antes de usar os estados "
            "para diagnóstico. A saída física da esteira é comandada pelo Ladder."
        )
        nota.setWordWrap(True)
        layout.addWidget(nota)
        layout.addStretch()
        return janela

    def ao_mudar_aba(self, indice):
        # A terceira aba funciona como atalho para a janela destacável.
        if indice == 2:
            self.abrir_monitoramento()
            self.abas.blockSignals(True)
            self.abas.setCurrentIndex(self._ultima_aba)
            self.abas.blockSignals(False)
        else:
            self._ultima_aba = indice

    def abrir_monitoramento(self):
        self.janela_monitoramento.show()
        self.janela_monitoramento.raise_()
        self.janela_monitoramento.activateWindow()

    def atualizar_estado_botao_esteira(self):
        """O botão pulsa %M8; cor/texto acompanham o estado lógico lido em %M9."""
        if not hasattr(self, "btn_esteira"):
            return
        estado = self.bits_memoria[9] if len(self.bits_memoria) > 9 else None
        pedido_pendente = 8 in self.comandos_pendentes
        if not self.conectado or estado is None:
            self.btn_esteira.setEnabled(False)
            self.btn_esteira.setText("ESTEIRA — SEM LEITURA")
            self.btn_esteira.setStyleSheet(
                "padding: 12px; font-weight: bold; background: #e0e0e0; color: #555;"
            )
        elif pedido_pendente:
            self.btn_esteira.setEnabled(False)
            self.btn_esteira.setText("SOLICITAÇÃO DA ESTEIRA ENVIADA…")
            self.btn_esteira.setStyleSheet(
                "padding: 12px; font-weight: bold; background: #fff2cc; color: #7f6000;"
            )
        elif estado:
            self.btn_esteira.setEnabled(True)
            self.btn_esteira.setText("DESLIGAR ESTEIRA")
            self.btn_esteira.setStyleSheet(
                "padding: 12px; font-weight: bold; background: #22a447; color: white;"
            )
        else:
            self.btn_esteira.setEnabled(True)
            self.btn_esteira.setText("LIGAR ESTEIRA")
            self.btn_esteira.setStyleSheet(
                "padding: 12px; font-weight: bold; background: #d93025; color: white;"
            )

    def criar_tela_atrito(self):
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        titulo = QLabel("PERDAS POR ATRITO")
        titulo.setStyleSheet("font-size: 22px; font-weight: bold; color: #243447;")
        subtitulo = QLabel("Acompanhe os valores calculados pelo CLP durante o ensaio.")
        subtitulo.setStyleSheet("color: #667085; font-size: 13px;")
        layout.addWidget(titulo)
        layout.addWidget(subtitulo)

        resumo = QGroupBox("Dados do ensaio")
        resumo.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #d0d7de; border-radius: 8px; margin-top: 8px; padding: 12px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        grid = QGridLayout(resumo)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        def campo(titulo_campo, valor_inicial):
            caixa = QGroupBox()
            caixa.setStyleSheet("QGroupBox { background: #f7f9fc; border: 1px solid #e0e5eb; border-radius: 7px; }")
            coluna = QVBoxLayout(caixa)
            nome = QLabel(titulo_campo)
            nome.setStyleSheet("color: #667085; font-size: 12px; font-weight: normal; border: none; background: transparent;")
            valor = QLabel(valor_inicial)
            valor.setStyleSheet("font-size: 19px; font-weight: bold; color: #243447; padding: 5px 0; border: none; background: transparent;")
            coluna.addWidget(nome)
            coluna.addWidget(valor)
            return caixa, valor

        c1, self.oscilacoes_label = campo("Semi-oscilações do ensaio", "11")
        c2, self.angulo_inicial_label = campo("Ângulo inicial", "-150.00°")
        c3, self.angulo_final_label = campo("Ângulo final (%MF106)", "-- °")
        c4, self.perda_atrito_label = campo("Energia perdida por atrito", "-- J")
        grid.addWidget(c1, 0, 0)
        grid.addWidget(c2, 0, 1)
        grid.addWidget(c3, 1, 0)
        grid.addWidget(c4, 1, 1)
        layout.addWidget(resumo)

        acoes = QGroupBox("Comando do ensaio")
        acoes_layout = QVBoxLayout(acoes)
        self.btn_perdas = QPushButton("INICIAR / SOLICITAR ENSAIO DE ATRITO")
        self.btn_perdas.setEnabled(False)
        self.btn_perdas.setStyleSheet("padding: 12px; font-weight: bold; background: #d9eaf7;")
        self.btn_perdas.clicked.connect(lambda: self.enviar_comando(105, "Ensaio de perdas por atrito"))
        acoes_layout.addWidget(self.btn_perdas)
        layout.addWidget(acoes)

        nota = QLabel(
            "Valores de referência: 11 semi-oscilações e ângulo inicial de -150°. "
            "O ângulo final é lido de %MF106 e a energia perdida por atrito de %MF120. "
            "O botão envia um pulso de solicitação para %M105. A memória %M5 indica que "
            "o ensaio está em andamento; enquanto %M5 estiver ativa, o botão fica bloqueado. "
            "O Ladder deve validar as permissões antes de iniciar."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #667085; font-size: 12px; padding: 4px;")
        layout.addWidget(nota)
        layout.addStretch()
        return pagina

    def enviar_energia_nominal(self):
        """Escreve a energia nominal em %MF6 somente quando solicitado pelo usuário."""
        if not self.conectado:
            QMessageBox.warning(self, "CLP desconectado", "Conecte-se ao CLP antes de enviar a energia nominal.")
            return

        valor = float(self.energia_nominal.value())
        # REAL IEEE-754 32-bit em duas words, com palavra baixa primeiro,
        # conforme a ordem já confirmada nas leituras de %MF2/%MF4.
        word_alta, word_baixa = struct.unpack(">HH", struct.pack(">f", valor))
        cliente = ModbusTcpClient(host=IP_CLP, port=PORTA_MODBUS, timeout=2)
        try:
            if not cliente.connect():
                raise RuntimeError("Falha ao conectar ao CLP.")
            resposta = cliente.write_registers(
                address=6, values=[word_baixa, word_alta], slave=UNIT_ID
            )
            if resposta.isError():
                raise RuntimeError(str(resposta))
            QMessageBox.information(
                self, "Energia enviada",
                f"Valor {valor:.2f} J enviado para %MF6.\n"
                "Confira no EcoStruxure se o valor foi recebido corretamente."
            )
            self.status.setText(f"Energia nominal {valor:.2f} J enviada para %MF6.")
        except Exception as erro:
            QMessageBox.critical(self, "Falha ao enviar energia", f"Não foi possível escrever %MF6:\n{erro}")
        finally:
            cliente.close()

    def enviar_comando(self, endereco, nome, confirmar=False):
        if not self.conectado:
            QMessageBox.warning(self, "CLP desconectado", "Não é possível enviar o comando: o CLP não está conectado.")
            return
        if confirmar:
            resposta = QMessageBox.warning(
                self, "Confirmar impacto",
                "O comando de impacto pode liberar o pêndulo para queda livre. "
                "Confirme que a área está isolada e que a máquina está pronta. Deseja enviar o pedido?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
        if endereco in self.comandos_pendentes:
            return
        if endereco == 105 and (self.ensaio_atrito_ativo or self.solicitacao_atrito_pendente):
            return
        if endereco == 105:
            self.solicitacao_atrito_pendente = True
            self.atualizar_estado_botao_atrito()
            # Se o CLP não sinalizar início, libera a solicitação após 5 s.
            QTimer.singleShot(5000, self.liberar_pedido_atrito_se_nao_iniciou)
        cliente = ModbusTcpClient(host=IP_CLP, port=PORTA_MODBUS, timeout=2)
        try:
            if not cliente.connect():
                raise RuntimeError("Falha ao conectar ao CLP.")
            escrita = cliente.write_coil(address=endereco, value=True, slave=UNIT_ID)
            if escrita.isError():
                raise RuntimeError(str(escrita))
            self.comandos_pendentes.add(endereco)
            self.status.setText(f"Pedido enviado: {nome} (%M{endereco}) — pulso de 250 ms")
            QTimer.singleShot(250, lambda: self.finalizar_pulso(endereco, nome))
        except Exception as erro:
            if endereco == 105:
                self.solicitacao_atrito_pendente = False
                self.atualizar_estado_botao_atrito()
            QMessageBox.critical(self, "Falha no comando", f"Não foi possível enviar {nome}:\n{erro}")
        finally:
            cliente.close()

    def finalizar_pulso(self, endereco, nome):
        cliente = ModbusTcpClient(host=IP_CLP, port=PORTA_MODBUS, timeout=2)
        try:
            if not cliente.connect():
                raise RuntimeError("Não foi possível reconectar para liberar o pedido.")
            resposta = cliente.write_coil(address=endereco, value=False, slave=UNIT_ID)
            if resposta.isError():
                raise RuntimeError(str(resposta))
            self.status.setText(f"Pulso de {nome} concluído; %M{endereco} solicitado para 0.")
        except Exception as erro:
            QMessageBox.critical(
                self, "Atenção: falha ao liberar pedido",
                f"O comando {nome} foi enviado, mas não foi possível garantir a escrita de FALSE em %M{endereco}.\n"
                f"Verifique a memória no EcoStruxure antes de continuar.\n{erro}"
            )
        finally:
            self.comandos_pendentes.discard(endereco)
            cliente.close()
            if endereco == 8:
                self.atualizar_estado_botao_esteira()

    def liberar_pedido_atrito_se_nao_iniciou(self):
        if not self.ensaio_atrito_ativo:
            self.solicitacao_atrito_pendente = False
            self.atualizar_estado_botao_atrito()

    def atualizar_estado_botao_atrito(self):
        if not hasattr(self, "btn_perdas"):
            return
        if not self.conectado:
            self.btn_perdas.setEnabled(False)
            self.btn_perdas.setText("CLP DESCONECTADO")
        elif self.ensaio_atrito_ativo:
            self.btn_perdas.setEnabled(False)
            self.btn_perdas.setText("ENSAIO DE ATRITO EM ANDAMENTO…")
            self.btn_perdas.setStyleSheet("padding: 12px; font-weight: bold; background: #fff2cc; color: #7f6000;")
        elif self.solicitacao_atrito_pendente:
            self.btn_perdas.setEnabled(False)
            self.btn_perdas.setText("SOLICITAÇÃO ENVIADA — AGUARDANDO CLP…")
            self.btn_perdas.setStyleSheet("padding: 12px; font-weight: bold; background: #fff2cc; color: #7f6000;")
        else:
            self.btn_perdas.setEnabled(True)
            self.btn_perdas.setText("INICIAR ENSAIO DE ATRITO")
            self.btn_perdas.setStyleSheet("padding: 12px; font-weight: bold; background: #d9eaf7;")

    def receber_dados(self, angulo, pico, energia, perda_atrito, angulo_final, bits):
        self.angulo = angulo
        self.pico_angulo = pico
        self.energia_absorvida = energia
        self.perda_atrito = perda_atrito if math.isfinite(perda_atrito) else None
        self.angulo_final_atrito = angulo_final if math.isfinite(angulo_final) else None
        self.bits_memoria = bits
        # %M5 é o estado real do ensaio de atrito no Ladder.
        estado_m5 = bits[5] if len(bits) > 5 else None
        if estado_m5 is not None:
            self.ensaio_atrito_ativo = bool(estado_m5)
            if self.ensaio_atrito_ativo:
                self.solicitacao_atrito_pendente = False
            elif not self.solicitacao_atrito_pendente:
                self.ensaio_atrito_ativo = False
        self.atualizar_tela()
        self.atualizar_estado_botao_atrito()
        self.atualizar_estado_botao_esteira()

    def atualizar_status(self, mensagem, conectado):
        self.conectado = conectado
        self.status.setText(mensagem)
        for botao in (self.btn_subir, self.btn_descer, self.btn_zerar, self.btn_impacto, self.btn_enviar_energia):
            botao.setEnabled(conectado)
        if not conectado:
            self.ensaio_atrito_ativo = False
            self.solicitacao_atrito_pendente = False
        self.atualizar_estado_botao_atrito()
        self.atualizar_estado_botao_esteira()
        if not conectado and hasattr(self, "angulo_label"):
            self.angulo = None
            self.pico_angulo = None
            self.energia_absorvida = None
            self.perda_atrito = None
            self.angulo_final_atrito = None
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
        self.angulo_final_label.setText(
            f"{self.angulo_final_atrito:.2f}°"
            if self.angulo_final_atrito is not None else "-- °"
        )

        for i, label in self.indicadores_memoria.items():
            bit = self.bits_memoria[i] if i < len(self.bits_memoria) else None
            if bit is None:
                estado = "NÃO LIDO — CONFIRMAR MAPA"
                cor_bola = "#9e9e9e"  # cinza: estado não lido
            elif bit:
                estado = "ATIVA (1)"
                cor_bola = "#22a447"  # verde: memória em 1
            else:
                estado = "INATIVA (0)"
                cor_bola = "#d93025"  # vermelho: memória em 0

            label.setText(
                f"%M{i} — {self.NOMES_MEMORIAS[i]}: {estado} "
                f'<span style="color:{cor_bola}; font-size:18px;">●</span>'
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
