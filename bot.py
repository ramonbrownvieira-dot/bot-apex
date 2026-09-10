import ccxt
import time
import threading
from flask import Flask

# Servidor Web leve para manter o Render ativo
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot APEX está rodando 24/7!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Configuração da API Testnet (Demo Binance)
exchange = ccxt.binance({
    'apiKey': '7lCdmhEJbzK6InKnU0O0AuSBQL5x1k4qNVqG2m9a6TtrnUrgP1BuEXD2MG7tkzVa',
    'secret': 'YfLMKP6GPATh3RhiCPhfwOXyAoy45zEWnOBmiyRoNUXPuux9Ir2PntqLtMhT2BWA',
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
exchange.set_sandbox_mode(True)

SYMBOL = 'TUSDT'
LEVERAGE = 10
CAPITAL_USDT = 2.0
PARCIAL_PCT = 0.0340
TRAVA_0X0_PCT = 0.0576
REPIQUE_PCT = 0.0172
COOLDOWN_SEGUNDOS = 600

def loop_bot():
    print("🤖 Bot APEX iniciado e rodando na nuvem 24/7...")
    while True:
        try:
            print("🚀 [PASSO 1] Iniciando ciclo automático...")
            # Lógica de ordens entrará aqui
            print(f"⏳ [PASSO 4] Ciclo concluído. Aguardando 10 minutos de Cooldown...\n")
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}")
            time.sleep(30)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    loop_bot()
