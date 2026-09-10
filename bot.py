import ccxt
import time
import threading
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot APEX - Teste Rápido de Velocidade Ativo!", 200

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

SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')                  
LEVERAGE = 10                                             
CAPITAL_USDT = float(os.getenv('CAPITAL_USDT', 10.0))   

# -------------------------------------------------------------------
# MODO TESTE DE VELOCIDADE (PARCIAL ULTRA-CURTA: 0.15%)
# -------------------------------------------------------------------
PARCIAL_PCT = 0.0015                                       # 0.15% (Disparo Rápido)
PCT_FECHAR_VENCEDOR = 0.85                                 # 85%
PCT_FECHAR_PERDEDOR = 0.15                                 # 15%

TRAVA_0X0_PCT = 0.0030                                     # Trava distante só para proteção no teste
ALVO_FINAL_PCT = 0.0010                                    # Repique rápido

COOLDOWN_SEGUNDOS = 120                                    # Cooldown reduzido para 2 min nos testes

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
            print(f"⚠️ Aguardando Fills na Binance... ({e})", flush=True)
        time.sleep(0.3)

    return preco_fallback

def obter_preco_atual():
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        return float(ticker['last'])
    except Exception as e:
        print(f"⚠️ Erro ao consultar preço de mercado: {e}", flush=True)
        return None

def obter_margem_posicao_usdt(lado_posicao):
    """
    Retorna a margem alocada atual (em USDT) para o lado da posição.
    """
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for pos in positions:
            if pos['side'].upper() == lado_posicao.upper():
                # Captura a margem isolada/inicial da posição
                margem = float(pos.get('initialMargin', 0) or pos.get('info', {}).get('initialMargin', 0))
                return margem
    except Exception as e:
        print(f"⚠️ Erro ao ler margem da posição {lado_posicao}: {e}", flush=True)
    return 0.0

def executar_ciclo():
    print(f"⚡ [TESTE RÁPIDO] Executando entradas no par {SYMBOL} (Parcial em 0.15%)...", flush=True)
    
    exchange.load_markets()
    
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta ao definir alavancagem: {e}", flush=True)
    
    precio_atual = obter_preco_atual()
    
    # Garantir quantidade operacional mínima para evitar truncamento em BTC
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    if qtd_moedas < 0.002:
        qtd_moedas = 0.002
    
    # 1. Abertura Long/Short
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    time.sleep(0.5)
    
    # 2. Preço Médio Ponderado ($P_{ref}$) Real via Fills
    p_long = obter_preco_executado_real(ordem_long.get('id'), precio_atual)
    p_short = obter_preco_executado_real(ordem_short.get('id'), precio_atual)
    p_ref = (p_long + p_short) / 2.0
    
    # 3. Guardar a Margem Inicial de cada lado logo após a abertura
    margem_inicial_long = obter_margem_posicao_usdt('LONG')
    margem_inicial_short = obter_margem_posicao_usdt('SHORT')
    
    # Se a API demorar a retornar a margem, usamos a estimativa de $10 USD
    if margem_inicial_long == 0.0: margem_inicial_long = CAPITAL_USDT
    if margem_inicial_short == 0.0: margem_inicial_short = CAPITAL_USDT
    
    print(f"✅ Fills OK! PMP: {p_ref:.2f} | Margem Long Início: ${margem_inicial_long:.2f} | Margem Short Início: ${margem_inicial_short:.2f}", flush=True)
    
    # 4. Preços dos Triggers (0.15% Parcial)
    p_parcial_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    p_0x0_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    p_alvo_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT)))
    
    p_parcial_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + PARCIAL_PCT)))
    p_0x0_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + TRAVA_0X0_PCT)))
    p_alvo_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + ALVO_FINAL_PCT)))
    
    qtd_parcial_vencedor = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * PCT_FECHAR_VENCEDOR))
    qtd_parcial_perdedor = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * PCT_FECHAR_PERDEDOR))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📌 TESTE -> Parcial Queda: {p_parcial_baixa:.2f} | Parcial Alta: {p_parcial_alta:.2f}", flush=True)
    
    # 5. Armar Ordens Condicionais
    # Lado da Queda
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_vencedor, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_perdedor, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
    })
    
    # Lado da Alta
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_parcial_perdedor, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_parcial_vencedor, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
    })
    
    print("⏳ Ordens no book! Monitorando alterações de MARGEM em tempo real (delay 1s)...", flush=True)
    
    # 6. Monitoramento de Alta Velocidade pela Margem (Loop de 1s)
    lado_atingido = None
    
    while True:
        margem_long_atual = obter_margem_posicao_usdt('LONG')
        margem_short_atual = obter_margem_posicao_usdt('SHORT')
        p_mercado = obter_preco_atual()
        
        # Se a margem do Short caiu significativamente, a Parcial de Queda rodou!
        if 0 < margem_short_atual < (margem_inicial_short * 0.70):
            print(f"🎯 [DETECÇÃO INSTANTÂNEA] Margem Short caiu de ${margem_inicial_short:.2f} para ${margem_short_atual:.2f} -> PARCIAL DE QUEDA EXECUTADA!", flush=True)
            lado_atingido = 'QUEDA'
            break
            
        # Se a margem do Long caiu significativamente, a Parcial de Alta rodou!
        if 0 < margem_long_atual < (margem_inicial_long * 0.70):
            print(f"🎯 [DETECÇÃO INSTANTÂNEA] Margem Long caiu de ${margem_inicial_long:.2f} para ${margem_long_atual:.2f} -> PARCIAL DE ALTA EXECUTADA!", flush=True)
            lado_atingido = 'ALTA'
            break
            
        if p_mercado and (p_mercado <= p_0x0_baixa or p_mercado >= p_0x0_alta):
            print(f"🏁 Trava 0x0 atingida no preço! Cotação: {p_mercado:.2f}", flush=True)
            try:
                exchange.cancel_all_orders(SYMBOL)
            except:
                pass
            return
            
        time.sleep(1)
    
    # 7. FASE 2: Expurgar ordens antigas imediatamente
    if lado_atingido:
        print(f"🧹 [REMOVENDO LIXO] Cancelando ordens remanescentes...", flush=True)
        try:
            exchange.cancel_all_orders(SYMBOL)
            print("✅ Book 100% Limpo!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao cancelar ordens: {e}", flush=True)
            
        print(f"🚀 [FASE 2] Posicionando Alvo do Repique no book...", flush=True)
        
        qtd_alvo_vencedor_restante = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * (1.0 - PCT_FECHAR_VENCEDOR)))
        qtd_alvo_perdedor_restante = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * (1.0 - PCT_FECHAR_PERDEDOR)))
        
        try:
            if lado_atingido == 'QUEDA':
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_alvo_vencedor_restante, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_alvo_perdedor_restante, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
            elif lado_atingido == 'ALTA':
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_alvo_perdedor_restante, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_alvo_vencedor_restante, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
            print("🛡️ [FASE 2 OK] Alvo de Repique posicionado com sucesso!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta Fase 2: {e}", flush=True)
            
        while True:
            try:
                ordens_ativas = exchange.fetch_open_orders(SYMBOL)
                if len(ordens_ativas) == 0:
                    print(f"🏁 Ciclo concluído com sucesso!", flush=True)
                    break
            except:
                pass
            time.sleep(3)

def loop_bot():
    print("🤖 Bot APEX - Modo Teste de Alta Velocidade Ativo...", flush=True)
    while True:
        try:
            executar_ciclo()
            print(f"⏳ Operação concluída. Cooldown de {COOLDOWN_SEGUNDOS} segundos...\n", flush=True)
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}", flush=True)
            time.sleep(10)

if __name__ == '__main__':
    t = threading.Thread(target=loop_bot, daemon=True)
    t.start()
    run_flask()
