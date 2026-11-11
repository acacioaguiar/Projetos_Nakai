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
