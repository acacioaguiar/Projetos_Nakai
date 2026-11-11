
from pymodbus.client import ModbusTcpClient
import time

IP_CLP = "10.0.0.20"
PORTA = 502
UNIT_ID = 1

# Memórias que serão testadas
MEMORIAS = {
    "%M100": 100,
    "%M101": 101,
    "%M102": 102,
    "%M103": 103,
}

cliente = ModbusTcpClient(
    IP_CLP,
    port=PORTA,
    timeout=2
)


def escrever_memoria(endereco, valor):
    resposta = cliente.write_coil(
        address=endereco,
        value=valor,
        slave=UNIT_ID
    )

    if resposta.isError():
        print(f"  ERRO ao escrever: {resposta}")
        return False

    print(f"  Escrita solicitada: {valor}")
    return True


def ler_memoria(endereco):
    resposta = cliente.read_coils(
        address=endereco,
        count=1,
        slave=UNIT_ID
    )

    if resposta.isError():
        print(f"  ERRO ao ler: {resposta}")
        return None

    return resposta.bits[0]


try:
    if not cliente.connect():
        print("Falha ao conectar ao CLP.")
    else:
        print("Conectado ao CLP.")
        print("Iniciando teste das memórias...\n")

        for nome, endereco in MEMORIAS.items():
            print(f"Testando {nome} (endereço Modbus {endereco})")

            # Testa primeiro True
            if escrever_memoria(endereco, True):
                time.sleep(0.2)
                valor = ler_memoria(endereco)
                print(f"  Leitura após True: {valor}")

            time.sleep(0.5)

            # Testa depois False
            if escrever_memoria(endereco, False):
                time.sleep(0.2)
                valor = ler_memoria(endereco)
                print(f"  Leitura após False: {valor}")

            print()
            time.sleep(0.5)

        print("Teste concluído.")

finally:
    if cliente.connected:
        # Garante que todas as memórias testadas terminem em False
        for endereco in MEMORIAS.values():
            cliente.write_coil(
                address=endereco,
                value=False,
                slave=UNIT_ID
            )

    cliente.close()

input("\nPressione Enter para fechar...")

