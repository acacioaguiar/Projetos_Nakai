
import struct
from pymodbus.client import ModbusTcpClient

IP_CLP = "10.0.0.20"
PORTA = 502

def interpretar_float(palavra1, palavra2):
    normal = struct.unpack(
        ">f", struct.pack(">HH", palavra1, palavra2)
    )[0]

    invertido = struct.unpack(
        ">f", struct.pack(">HH", palavra2, palavra1)
    )[0]

    return normal, invertido

client = ModbusTcpClient(
    host=IP_CLP,
    port=PORTA,
    timeout=3
)

try:
    if not client.connect():
        print("ERRO: nao foi possivel conectar ao CLP.")
    else:
        print("Conexao estabelecida.")

        # Leitura somente: %MW2 ate %MW5
        resposta = client.read_holding_registers(
            address=2,
            count=4,
            slave=1
        )

        if resposta.isError():
            print("Erro Modbus:", resposta)
        else:
            regs = resposta.registers

            print("Registradores brutos:", regs)
            print("Possiveis valores para %MF2:")
            print("  Ordem normal:", interpretar_float(regs[0], regs[1])[0])
            print("  Ordem invertida:", interpretar_float(regs[0], regs[1])[1])

            print("Possiveis valores para %MF4:")
            print("  Ordem normal:", interpretar_float(regs[2], regs[3])[0])
            print("  Ordem invertida:", interpretar_float(regs[2], regs[3])[1])

finally:
    client.close()
    print("Conexao encerrada.")
