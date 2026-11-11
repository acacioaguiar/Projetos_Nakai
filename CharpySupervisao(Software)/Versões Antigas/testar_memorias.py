
from pymodbus.client import ModbusTcpClient

IP_CLP = "10.0.0.20"
UNIT_ID = 1

cliente = ModbusTcpClient(IP_CLP, port=502, timeout=2)

try:
    if not cliente.connect():
        print("Falha ao conectar ao CLP.")
    else:
        resposta = cliente.read_coils(
            address=0,
            count=5,
            slave=UNIT_ID
        )

        if resposta.isError():
            print("Leitura de coils recusada:", resposta)
        else:
            for i, estado in enumerate(resposta.bits[:5]):
                print(f"%M{i} = {estado}")

finally:
    cliente.close()

input("Pressione Enter para fechar...")

