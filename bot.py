import ccxt
import time
import threading
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot APEX está rodando 24/7!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True
    }
})

exchange.enable_demo_trading(True)

SYMBOL = 'TUSDT'
LEVERAGE = 10
CAPITAL_USDT = float(os.getenv('CAPITAL_USDT', 2.0))     # Capital por lado ($)

# -------------------------------------------------------------------
# PARAMETRIZAÇÃO DA PARCIAL (ÚNICA VARIÁVEL DE ENTRADA)
# -------------------------------------------------------------------
PARCIAL_PCT = float(os.getenv('PARCIAL_PCT', 0.0050))     # Ex: 0.0050 = 0.50% | 0.0340 = 3.40%

# DERIVAÇÃO AUTOMÁTICA DOS DEMAIS NÍVEIS
TRAVA_0X0_PCT = round(PARCIAL_PCT * (0.0576 / 0.0340), 6) # Proporção da Trava 0x0
ALVO_FINAL_PCT = round(PARCIAL_PCT / 2.0, 6)               # Alvo Final = Metade da distância (Repique)

COOLDOWN_SEGUNDOS = 600    # 10 minutos após finalização do ciclo

def obter_preco_medio_executado(ordem, preco_fallback):
    """Extrai o preço médio real executado da ordem na Binance."""
    if not ordem:
        return preco_fallback
    
    avg_price = ordem.get('average') or ordem.get('price')
    if avg_price and float(avg_price) > 0:
        return float(avg_price)
    
    trades = ordem.get('trades') or []
    if trades:
        total_qty = sum(float(t.get('amount', 0)) for t in trades)
        if total_qty > 0:
            total_cost = sum(float(t.get('amount', 0)) * float(t.get('price', 0)) for t in trades)
            return total_cost / total_qty
            
    return preco_fallback

def obter_preco_atual():
    """Consulta a cotação em tempo real via Ticker (Zero delay)."""
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        return float(ticker['last'])
    except Exception as e:
        print(f"⚠️ Erro ao consultar preço de mercado: {e}", flush=True)
        return None

def executar_ciclo():
    print("🚀 [FASE 1] Executando entradas a mercado e armando ordens bidirecionais...", flush=True)
    
    exchange.load_markets()
    
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta ao definir alavancagem: {e}", flush=True)
    
    precio_atual = obter_preco_atual()
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    
    # 1. Abertura a Mercado em Hedge Mode
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    # 2. Leitura dos Preços Médios Reais Executados
    p_long = obter_preco_medio_executado(ordem_long, precio_atual)
    p_short = obter_preco_medio_executado(ordem_short, precio_atual)
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Execução Real: Long {p_long:.6f} | Short {p_short:.6f} | Preço Ref PMP: {p_ref:.6f}", flush=True)
    
    # 3. Cálculo dos Níveis de Preço (Alta e Queda)
    # Queda
    p_parcial_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    p_0x0_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    p_alvo_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT))) # Repique na Metade
    
    # Alta
    p_parcial_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + PARCIAL_PCT)))
    p_0x0_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + TRAVA_0X0_PCT)))
    p_alvo_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + ALVO_FINAL_PCT)))  # Repique na Metade
    
    qtd_parcial_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.85))
    qtd_parcial_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.30))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📊 Porcentagens: Parcial {PARCIAL_PCT*100:.2f}% | Trava 0x0 {TRAVA_0X0_PCT*100:.2f}% | Alvo Repique {ALVO_FINAL_PCT*100:.3f}%", flush=True)
    print(f"📌 Queda -> Parcial: {p_parcial_baixa} | 0x0: {p_0x0_baixa} | Alvo Repique: {p_alvo_baixa}", flush=True)
    print(f"📌 Alta  -> Parcial: {p_parcial_alta} | 0x0: {p_0x0_alta} | Alvo Repique: {p_alvo_alta}", flush=True)
    
    # 4. Posicionar Ordens Condicionais no Book da Binance
    # Lado da Queda
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_long, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_total, None, {
        'positionSide': 'LONG', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
    })
    
    # Lado da Alta
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_parcial_long, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_total, None, {
        'positionSide': 'LONG', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
    })
    
    print("⏳ [FASE 1 OK] Posições e proteções armadas para ALTA e QUEDA. Monitorando cotação...", flush=True)
    
    # 5. MONITORAMENTO DE PREÇO DA FASE 1
    lado_atingido = None
    
    while True:
        p_mercado = obter_preco_atual()
        if not p_mercado:
            time.sleep(3)
            continue
            
        # Verificação de Travas 0x0
        if p_mercado <= p_0x0_baixa or p_mercado >= p_0x0_alta:
            print(f"🏁 Trava 0x0 atingida no preço! Cotação: {p_mercado:.6f}", flush=True)
            return
            
        # Verificação de Parcial na Queda
        if p_mercado <= p_parcial_baixa:
            print(f"🎯 PARCIAL DE QUEDA ATINGIDA! Cotação: {p_mercado:.6f} <= {p_parcial_baixa:.6f}", flush=True)
            lado_atingido = 'QUEDA'
            break
            
        # Verificação de Parcial na Alta
        if p_mercado >= p_parcial_alta:
            print(f"🎯 PARCIAL DE ALTA ATINGIDA! Cotação: {p_mercado:.6f} >= {p_parcial_alta:.6f}", flush=True)
            lado_atingido = 'ALTA'
            break
            
        time.sleep(3)
    
    # 6. FASE 2: Posicionar Alvo Final (Repique) no book
    if lado_atingido:
        print(f"🚀 [FASE 2] Posicionando Alvo de Repique do movimento de {lado_atingido}...", flush=True)
        
        qtd_alvo_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.15))
        qtd_alvo_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.70))
        
        try:
            if lado_atingido == 'QUEDA':
                # No repique da queda, o preço sobe de volta em direção ao alvo
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_alvo_short, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_alvo_long, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
            elif lado_atingido == 'ALTA':
                # No repique da alta, o preço cai de volta em direção ao alvo
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_alvo_long, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_alvo_short, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
            print("🛡️ [FASE 2 OK] Alvos de repique armados no book!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao posicionar alvo final: {e}", flush=True)
            
        # Monitora a cotação até o encerramento do repique ou 0x0
        while True:
            p_mercado = obter_preco_atual()
            if not p_mercado:
                time.sleep(3)
                continue
                
            if lado_atingido == 'QUEDA' and (p_mercado >= p_alvo_baixa or p_mercado <= p_0x0_baixa):
                print(f"🏁 Operação de Queda finalizada no Repique/0x0! Cotação: {p_mercado:.6f}", flush=True)
                break
            elif lado_atingido == 'ALTA' and (p_mercado <= p_alvo_alta or p_mercado >= p_0x0_alta):
                print(f"🏁 Operação de Alta finalizada no Repique/0x0! Cotação: {p_mercado:.6f}", flush=True)
                break
                
            time.sleep(3)

def loop_bot():
    print("🤖 Bot APEX iniciado na nuvem (Europa - Demo Trading)...", flush=True)
    while True:
        try:
            executar_ciclo()
            print(f"⏳ Operação concluída. Aguardando Cooldown de {COOLDOWN_SEGUNDOS/60} minutos...\n", flush=True)
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}", flush=True)
            time.sleep(15)

if __name__ == '__main__':
    t = threading.Thread(target=loop_bot, daemon=True)
    t.start()
    run_flask()
