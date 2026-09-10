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
CAPITAL_USDT = float(os.getenv('CAPITAL_USDT', 5.0))     # Subido para $5 para sustentar a margem livre

# PARAMETRIZAÇÃO MODELO PRÁTICO (Ajustado para 1.00% de teste)
PARCIAL_PCT = float(os.getenv('PARCIAL_PCT', 0.0100))     # 1.00% para teste limpo
TAXA_ESTIMADA_PCT = 0.0020                                 # Taxas (0.20%)

TRAVA_0X0_PCT = round((PARCIAL_PCT * 1.6941) + TAXA_ESTIMADA_PCT, 6) 
ALVO_FINAL_PCT = round(PARCIAL_PCT / 2.0, 6)                          

COOLDOWN_SEGUNDOS = 600

def obter_preco_executado_real(ordem_id, preco_fallback):
    if not ordem_id:
        return preco_fallback

    for _ in range(3):
        try:
            trades = exchange.fetch_my_trades(SYMBOL, params={'orderId': str(ordem_id)})
            if trades:
                total_qty = sum(float(t['amount']) for t in trades)
                if total_qty > 0:
                    total_cost = sum(float(t['amount']) * float(t['price']) for t in trades)
                    return total_cost / total_qty
        except Exception as e:
            print(f"⚠️ Aguardando Fills na Binance para ordem {ordem_id}... ({e})", flush=True)
        time.sleep(0.5)

    return preco_fallback

def obter_preco_atual():
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        return float(ticker['last'])
    except Exception as e:
        print(f"⚠️ Erro ao consultar preço de mercado: {e}", flush=True)
        return None

def obter_ids_ordens_abertas():
    """Consulta os IDs de todas as ordens condicionais ativas no book da Binance."""
    try:
        ordens = exchange.fetch_open_orders(SYMBOL, params={'type': 'all'})
        return [str(o['id']) for o in ordens]
    except Exception as e:
        print(f"⚠️ Erro ao consultar ordens abertas: {e}", flush=True)
        return []

def executar_ciclo():
    print("🚀 [FASE 1] Executando entradas a mercado e armando ordens no book...", flush=True)
    
    exchange.load_markets()
    
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta ao definir alavancagem: {e}", flush=True)
    
    precio_atual = obter_preco_atual()
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    
    # 1. Abertura Long/Short simultânea
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    time.sleep(0.5)
    
    # 2. Preço Médio Ponderado ($P_ref$) Real via Fills
    p_long = obter_preco_executado_real(ordem_long.get('id'), precio_atual)
    p_short = obter_preco_executado_real(ordem_short.get('id'), precio_atual)
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Execução Real Fills: Long {p_long:.6f} | Short {p_short:.6f} | Preço Ref PMP: {p_ref:.6f}", flush=True)
    
    # 3. Níveis de Preço
    p_parcial_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    p_0x0_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    p_alvo_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT)))
    
    p_parcial_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + PARCIAL_PCT)))
    p_0x0_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + TRAVA_0X0_PCT)))
    p_alvo_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + ALVO_FINAL_PCT)))
    
    qtd_parcial_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.85))
    qtd_parcial_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.30))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📊 Parcial: {PARCIAL_PCT*100:.2f}% | Trava 0x0 c/ Taxas: {TRAVA_0X0_PCT*100:.2f}% | Alvo Repique: {ALVO_FINAL_PCT*100:.3f}%", flush=True)
    print(f"📌 Queda -> Parcial: {p_parcial_baixa} | 0x0: {p_0x0_baixa} | Alvo Repique: {p_alvo_baixa}", flush=True)
    print(f"📌 Alta  -> Parcial: {p_parcial_alta} | 0x0: {p_0x0_alta} | Alvo Repique: {p_alvo_alta}", flush=True)
    
    # 4. Posicionar Ordens Condicionais
    # Lado da Queda
    o_p_baixa_short = exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_short, None, {
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
    o_p_alta_long = exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_parcial_long, None, {
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
    
    id_p_baixa = str(o_p_baixa_short['id'])
    id_p_alta = str(o_p_alta_long['id'])
    
    print("⏳ [FASE 1 OK] Ordens armadas no book. Monitorando execuções reais...", flush=True)
    
    # Pausa de 5 segundos para o mercado assentar o spread inicial
    time.sleep(5)
    
    # 5. Monitoramento da Fase 1 (Prioridade Total para Desaparecimento da Ordem no Book)
    lado_atingido = None
    
    while True:
        ids_ativas = obter_ids_ordens_abertas()
        p_mercado = obter_preco_atual()
        
        # 1. Checagem Principal: A ordem de parcial sumiu do book porque a Binance EXECUTOU?
        if id_p_alta not in ids_ativas:
            print(f"🎯 PARCIAL DE ALTA EXECUTADA NA BINANCE (Ordem sumiu do book)!", flush=True)
            lado_atingido = 'ALTA'
            break
            
        if id_p_baixa not in ids_ativas:
            print(f"🎯 PARCIAL DE QUEDA EXECUTADA NA BINANCE (Ordem sumiu do book)!", flush=True)
            lado_atingido = 'QUEDA'
            break
            
        # 2. Checagem Secundária: Trava 0x0
        if p_mercado and (p_mercado <= p_0x0_baixa or p_mercado >= p_0x0_alta):
            print(f"🏁 Trava 0x0 atingida no preço! Cotação: {p_mercado:.6f}", flush=True)
            try:
                exchange.cancel_all_orders(SYMBOL)
            except:
                pass
            return
            
        time.sleep(2)
    
    # 6. FASE 2: Limpar lixo e posicionar Alvo de Repique
    if lado_atingido:
        print(f"🧹 Limpando ordens antigas do book para liberar margem...", flush=True)
        try:
            exchange.cancel_all_orders(SYMBOL)
            print("✅ Book limpo com sucesso!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao cancelar ordens antigas: {e}", flush=True)
            
        print(f"🚀 [FASE 2] Posicionando Alvo de Repique de {lado_atingido}...", flush=True)
        
        qtd_alvo_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.15))
        qtd_alvo_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.70))
        
        try:
            if lado_atingido == 'QUEDA':
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_alvo_short, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_alvo_long, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
                })
            elif lado_atingido == 'ALTA':
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_alvo_long, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_alvo_short, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_total, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
                })
            print("🛡️ [FASE 2 OK] Alvo e Trava 0x0 do repique armados no book!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao posicionar alvo final: {e}", flush=True)
            
        # Monitora liquidação no repique
        while True:
            ids_ativas = obter_ids_ordens_abertas()
            if len(ids_ativas) == 0:
                print(f"🏁 Operação de {lado_atingido} finalizada no Repique/0x0!", flush=True)
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
