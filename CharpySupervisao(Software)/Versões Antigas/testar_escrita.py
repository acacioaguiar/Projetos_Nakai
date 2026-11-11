
from pymodbus.client import ModbusTcpClient

IP_CLP = "10.0.0.20"
UNIT_ID = 1

cliente = ModbusTcpClient(IP_CLP, port=502, timeout=2)

try:
    if not cliente.connect():
        print("Falha ao conectar ao CLP.")
    else:
        # Testa o bit de comando reservado %M20
        resposta = cliente.write_coil(
            address=20,
            value=True,
            slave=UNIT_ID
        )

        print("Resposta da escrita:", resposta)

        leitura = cliente.read_coils(
            address=20,
            count=1,
            slave=UNIT_ID
        )

        if leitura.isError():
            print("Erro na leitura:", leitura)
        else:
            print("%M20 =", leitura.bits[0])

        # Desliga o bit de teste
        cliente.write_coil(
            address=20,
            value=False,
            slave=UNIT_ID
        )

finally:
    cliente.close()

input("Pressione Enter para fechar...")
