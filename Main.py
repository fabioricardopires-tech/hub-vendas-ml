# main.py - VERSÃO FINAL REVISADA

import requests
import webbrowser
import hashlib
import base64
import os
import re
import json
from datetime import datetime, timedelta
import gspread
import pandas as pd
import time
import logging

# --- CONFIGURAÇÃO DO LOGGING (VERSÃO MANUAL E ROBUSTA) ---
log_file_path = 'data/hub_vendas.log'
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if logger.hasHandlers():
    logger.handlers.clear()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# --- CONFIGURAÇÕES ---
APP_ID = '6479891770749073'
SECRET_KEY = 'HfEEglLSoRO6mLeFK705DWRaF1dHlnDr'
REDIRECT_URI = 'https://www.google.com'
TOKEN_FILE = 'data/tokens.json'
LAST_RUN_FILE = 'data/last_run.json'
GOOGLE_CREDENTIALS_FILE = 'data/google_credentials.json'
GOOGLE_SHEET_NAME = 'Hub Vendas - Estoque Central'

def renovar_token(refresh_token ):
    logging.info(">>> ♻️ Renovando token de acesso...")
    url = 'https://api.mercadolibre.com/oauth/token'
    payload = {'grant_type': 'refresh_token', 'client_id': APP_ID, 'client_secret': SECRET_KEY, 'refresh_token': refresh_token}
    response = requests.post(url, json=payload )
    if response.status_code == 200:
        token_data = response.json()
        salvar_tokens(token_data)
        logging.info("✅ Token renovado e salvo com sucesso!")
        return token_data
    else:
        logging.error(f"❌ ERRO ao renovar token: {response.status_code}, {response.text}")
        return None

def obter_token_valido():
    tokens = carregar_tokens()
    if not tokens or 'expires_at' not in tokens: return None
    expires_at = datetime.fromisoformat(tokens['expires_at'])
    if expires_at < datetime.now() + timedelta(minutes=10):
        return renovar_token(tokens.get('refresh_token'))
    logging.info("✅ Token de acesso válido encontrado.")
    return tokens

def iniciar_autenticacao(interactive=False):
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8')
    code_verifier = re.sub('[^a-zA-Z0-9]+', '', code_verifier)
    code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode('utf-8')
    code_challenge = code_challenge.replace('=', '')
    auth_url = (f"https://auth.mercadolibre.com.br/authorization?response_type=code&client_id={APP_ID}&redirect_uri={REDIRECT_URI}"
                f"&code_challenge={code_challenge}&code_challenge_method=S256" )
    if not interactive: return auth_url, code_verifier
    webbrowser.open(auth_url)
    auth_code = input(">>> Cole o código de autorização (code) aqui: ")
    return obter_token_com_codigo(auth_code, code_verifier)

def obter_token_com_codigo(auth_code, code_verifier):
    url_token = 'https://api.mercadolibre.com/oauth/token'
    payload = {'grant_type': 'authorization_code', 'client_id': APP_ID, 'client_secret': SECRET_KEY, 
               'code': auth_code.strip( ), 'redirect_uri': REDIRECT_URI, 'code_verifier': code_verifier}
    response = requests.post(url_token, json=payload)
    if response.status_code == 200:
        token_data = response.json()
        salvar_tokens(token_data)
        return token_data
    else: return None

def salvar_tokens(token_data):
    tokens_antigos = carregar_tokens()
    if 'expires_in' in token_data:
        token_data['expires_at'] = (datetime.now() + timedelta(seconds=token_data['expires_in'])).isoformat()
    if 'refresh_token' not in token_data and tokens_antigos and 'refresh_token' in tokens_antigos:
        token_data['refresh_token'] = tokens_antigos['refresh_token']
    with open(TOKEN_FILE, 'w') as f: json.dump(token_data, f)

def carregar_tokens():
    if not os.path.exists(TOKEN_FILE): return None
    try:
        with open(TOKEN_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return None

def conectar_google_sheets():
    try:
        gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        worksheet = gc.open(GOOGLE_SHEET_NAME).sheet1
        logging.info("✅ Conectado ao Google Sheets com sucesso.")
        return worksheet
    except Exception as e:
        logging.error(f"❌ ERRO ao conectar com o Google Sheets: {e}")
        return None

def ler_estoque_online(worksheet):
    try:
        # Lê os dados como texto puro para evitar interpretações erradas
        data = worksheet.get_all_values() 
        headers = data.pop(0)
        df = pd.DataFrame(data, columns=headers)

        # Função para converter para número, tratando vírgula e ponto
        def safe_to_numeric(series):
            return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

        # Aplica a conversão segura nas colunas numéricas
        df['QUANTIDADE_LOCAL'] = safe_to_numeric(df['QUANTIDADE_LOCAL'])
        df['PRECO_CUSTO'] = safe_to_numeric(df['PRECO_CUSTO'])
        
        logging.info("✅ Dados da planilha lidos e processados.")
        return df
    except Exception as e:
        logging.error(f"❌ ERRO ao ler dados da planilha: {e}")
        return None


def atualizar_linha_estoque(sku, nova_quantidade, novo_custo):
    try:
        worksheet = conectar_google_sheets()
        if not worksheet: raise Exception("Falha ao reconectar com o Google Sheets.")
        cell = worksheet.find(sku)
        if not cell:
            logging.error(f"❌ ERRO: SKU '{sku}' não encontrado na planilha.")
            return False
        headers = worksheet.row_values(1)
        col_qtd = headers.index('QUANTIDADE_LOCAL') + 1
        col_custo = headers.index('PRECO_CUSTO') + 1
        worksheet.update_cell(cell.row, col_qtd, float(nova_quantidade))
        worksheet.update_cell(cell.row, col_custo, float(novo_custo))
        logging.info(f"✅ Planilha atualizada para o SKU {sku}. Nova Qtd: {nova_quantidade}, Novo Custo: {novo_custo}")
        return True
    except Exception as e:
        logging.error(f"❌ ERRO ao atualizar a linha na planilha: {e}")
        return False

def buscar_e_processar_vendas(access_token, estoque_df, worksheet):
    logging.info("="*45)
    logging.info(">>> 🔎 Etapa 1: Baixando vendas recentes...")
    logging.info("="*45)
    headers = {'Authorization': f'Bearer {access_token}'}
    user_info = requests.get('https://api.mercadolibre.com/users/me', headers=headers ).json()
    user_id = user_info['id']
    agora = datetime.now()
    if os.path.exists(LAST_RUN_FILE):
        with open(LAST_RUN_FILE, 'r') as f:
            last_run_iso = json.load(f)['last_run']
            data_inicio = datetime.fromisoformat(last_run_iso)
    else:
        data_inicio = agora - timedelta(days=1)
    logging.info(f"Buscando vendas desde: {data_inicio.strftime('%d/%m/%Y %H:%M')}")
    data_inicio_str = data_inicio.isoformat(timespec='milliseconds') + 'Z'
    url_pedidos = f'https://api.mercadolibre.com/orders/search?seller={user_id}&order.date_created.from={data_inicio_str}'
    response = requests.get(url_pedidos, headers=headers )
    if response.status_code != 200:
        logging.error(f"Erro ao buscar pedidos: {response.text}")
        return False
    pedidos = response.json().get('results', [])
    if not pedidos:
        logging.info("✅ Nenhuma venda nova encontrada.")
        with open(LAST_RUN_FILE, 'w') as f: json.dump({'last_run': agora.isoformat()}, f)
        return True
    logging.info(f"✅ Encontradas {len(pedidos)} novas vendas. Processando baixas no estoque...")
    mudancas_estoque = {}
    for pedido in pedidos:
        logging.info(f"--- Processando Pedido ID: {pedido['id']} ---")
        for item in pedido['order_items']:
            sku = item['item'].get('seller_sku')
            if not sku:
                data_pedido = datetime.fromisoformat(pedido['date_created']).replace(tzinfo=None)
                if data_pedido > datetime.now() - timedelta(hours=48):
                    logging.warning(f"  - ⚠️ AVISO: O item '{item['item']['title']}' (pedido recente) não possui SKU. Não é possível dar baixa.")
                continue
            if sku in estoque_df['SKU'].values:
                if sku not in mudancas_estoque:
                    mudancas_estoque[sku] = estoque_df.loc[estoque_df['SKU'] == sku, 'QUANTIDADE_LOCAL'].iloc[0]
                logging.info(f"  - Dando baixa no SKU: {sku} | Estoque antes: {mudancas_estoque[sku]}")
                mudancas_estoque[sku] -= item['quantity']
                logging.info(f"  - Estoque agora: {mudancas_estoque[sku]}")
            else:
                logging.warning(f"  - ⚠️ AVISO: SKU '{sku}' vendido mas não encontrado no seu arquivo de estoque.")
    if mudancas_estoque:
        headers_planilha = worksheet.row_values(1)
        col_qtd_index = headers_planilha.index('QUANTIDADE_LOCAL') + 1
        updates_para_planilha = []
        for sku, nova_qtd in mudancas_estoque.items():
            try:
                cell = worksheet.find(sku)
                updates_para_planilha.append({
                    'range': f'{gspread.utils.rowcol_to_a1(cell.row, col_qtd_index)}',
                    'values': [[float(nova_qtd)]],
                })
            except gspread.exceptions.CellNotFound:
                logging.warning(f"  - ⚠️ AVISO: SKU '{sku}' não encontrado na planilha durante a atualização em lote.")
        if updates_para_planilha:
            worksheet.batch_update(updates_para_planilha)
            logging.info("✅ Planilha Google atualizada com as baixas de estoque.")
    with open(LAST_RUN_FILE, 'w') as f: json.dump({'last_run': agora.isoformat()}, f)
    return True

def sincronizar_estoque_para_ml(access_token, estoque_df, worksheet):
    logging.info("="*50)
    logging.info(">>> 🔄 Etapa 2: Sincronizando estoque para o ML...")
    logging.info("="*50)
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    for index, row in estoque_df.iterrows():
        sku = row['SKU']
        estoque_local = row['QUANTIDADE_LOCAL']
        logging.info(f"\n--- Sincronizando SKU: {sku} | Estoque Local: {estoque_local} ---")
        for i in range(1, 6):
            id_anuncio_col = f'ID_ANUNCIO_{i}'
            logistica_col = f'LOGISTICA_{i}'
            if id_anuncio_col not in row or not row[id_anuncio_col]: continue
            id_anuncio = row[id_anuncio_col]
            logistica = row.get(logistica_col, 'self_service').lower()
            logging.info(f"  - Verificando anúncio {id_anuncio} ({logistica})...")
            if logistica != 'self_service':
                logging.warning("    - 🟡 Logística não é 'self_service'. Pulando sincronização de estoque.")
                continue
            url_item = f'https://api.mercadolibre.com/items/{id_anuncio}?attributes=available_quantity'
            try:
                resp_item = requests.get(url_item, headers={'Authorization': f'Bearer {access_token}'} )
                if resp_item.status_code != 200:
                    logging.error(f"    - ❌ Erro ao buscar anúncio {id_anuncio}. Resposta: {resp_item.text}")
                    continue
                estoque_ml = resp_item.json()['available_quantity']
                logging.info(f"    - Estoque no ML (atual):      {estoque_ml}")
                if int(estoque_local) != int(estoque_ml):
                    logging.info(f"    - ⚠️ Estoque divergente. Atualizando para {int(estoque_local)}...")
                    url_update = f'https://api.mercadolibre.com/items/{id_anuncio}'
                    payload = {'available_quantity': int(estoque_local )}
                    resp_update = requests.put(url_update, headers=headers, json=payload)
                    if resp_update.status_code == 200:
                        logging.info("    - ✅ SUCESSO! Anúncio atualizado.")
                    else:
                        logging.error(f"    - ❌ FALHA ao atualizar. Resposta: {resp_update.text}")
                else:
                    logging.info("    - ✅ Estoque já está sincronizado.")
                time.sleep(0.5)
            except Exception as e:
                logging.error(f"    - ❌ Ocorreu um erro inesperado ao processar o anúncio {id_anuncio}: {e}")

def analisar_financeiro_periodo(access_token, estoque_df, data_inicio, data_fim):
    logging.info(f"Iniciando análise financeira de {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
    headers = {'Authorization': f'Bearer {access_token}'}
    user_info = requests.get('https://api.mercadolibre.com/users/me', headers=headers ).json()
    user_id = user_info['id']
    data_inicio_str = data_inicio.strftime('%Y-%m-%dT00:00:00.000-00:00')
    data_fim_str = data_fim.strftime('%Y-%m-%dT23:59:59.999-00:00')
    url_pedidos = f'https://api.mercadolibre.com/orders/search?seller={user_id}&order.date_created.from={data_inicio_str}&order.date_created.to={data_fim_str}'
    response = requests.get(url_pedidos, headers=headers )
    if response.status_code != 200:
        logging.error(f"Erro ao buscar pedidos: {response.text}")
        return None
    pedidos = response.json().get('results', [])
    if not pedidos:
        logging.info("Nenhum pedido criado encontrado no período.")
        return pd.DataFrame()
    logging.info(f"Encontrados {len(pedidos)} pedidos. Filtrando por 'entregues' e analisando detalhes...")
    dados_vendas = []
    for pedido in pedidos:
        if 'delivered' not in pedido.get('tags', []): continue
        order_id = pedido['id']
        url_order_details = f'https://api.mercadolibre.com/orders/{order_id}'
        resp_order_details = requests.get(url_order_details, headers=headers )
        if resp_order_details.status_code != 200:
            logging.warning(f"Aviso: Falha ao buscar detalhes do pedido {order_id}. Status: {resp_order_details.status_code}")
            continue
        order_details = resp_order_details.json()
        custo_envio = order_details.get('shipping', {}).get('cost', 0)
        for item in order_details.get('order_items', []):
            sku = item['item'].get('seller_sku')
            preco_custo = 0
            if sku and sku in estoque_df['SKU'].values:
                preco_custo = estoque_df.loc[estoque_df['SKU'] == sku, 'PRECO_CUSTO'].iloc[0]
            valor_item = item.get('unit_price', 0) * item.get('quantity', 0)
            taxa_item = item.get('sale_fee', 0)
            custo_total_produto = preco_custo * item.get('quantity', 0)
            proporcao_item = valor_item / order_details.get('total_amount', 1) if order_details.get('total_amount', 0) > 0 else 0
            envio_rateado = custo_envio * proporcao_item
            lucro_bruto = valor_item - taxa_item - envio_rateado - custo_total_produto
            dados_vendas.append({
                'Data': datetime.fromisoformat(order_details['date_closed']).strftime('%d/%m/%Y'),
                'SKU': sku, 'Produto': item['item']['title'], 'Qtd': item.get('quantity', 0),
                'Valor Venda': valor_item, 'Taxa ML': taxa_item, 'Custo Envio': envio_rateado,
                'Custo Produto': custo_total_produto, 'Lucro Bruto': lucro_bruto
            })
    if not dados_vendas:
        logging.info("Nenhum pedido com status 'delivered' foi processado no período.")
        return pd.DataFrame()
    return pd.DataFrame(dados_vendas)

def registrar_compra_e_recalcular_custo(sku_alvo, qtd_comprada, custo_unitario_compra):
    """
    Registra uma nova compra, recalcula o custo médio ponderado e atualiza a planilha.
    """
    try:
        worksheet = conectar_google_sheets()
        if not worksheet:
            raise Exception("Falha ao reconectar com o Google Sheets.")
        try:
            cell = worksheet.find(sku_alvo)
        except gspread.exceptions.CellNotFound:
            logging.error(f"SKU '{sku_alvo}' não encontrado na planilha para registrar a compra.")
            return False, "SKU não encontrado."
        headers = worksheet.row_values(1)
        col_qtd_idx = headers.index('QUANTIDADE_LOCAL')
        col_custo_idx = headers.index('PRECO_CUSTO')
        linha_produto = worksheet.row_values(cell.row)
        qtd_atual = float(str(linha_produto[col_qtd_idx]).replace(',', '.'))
        custo_atual = float(str(linha_produto[col_custo_idx]).replace(',', '.'))
        logging.info(f"Dados atuais para {sku_alvo}: Qtd={qtd_atual}, Custo Médio Atual=R${custo_atual:.2f}")
        logging.info(f"Nova compra: Qtd={qtd_comprada}, Custo Unitário=R${custo_unitario_compra:.2f}")
        custo_total_antigo = qtd_atual * custo_atual
        custo_total_novo = float(qtd_comprada) * float(custo_unitario_compra)
        custo_total_geral = custo_total_antigo + custo_total_novo
        qtd_total_geral = qtd_atual + float(qtd_comprada)
        if qtd_total_geral > 0:
            # Arredonda o resultado para 2 casas decimais
            novo_custo_medio = round(custo_total_geral / qtd_total_geral, 2)
        else:
            novo_custo_medio = 0

            novo_custo_medio = 0
        logging.info(f"Cálculo: Nova Qtd Total={qtd_total_geral}, Novo Custo Médio=R${novo_custo_medio:.2f}")
        worksheet.update_cell(cell.row, col_qtd_idx + 1, qtd_total_geral)
        worksheet.update_cell(cell.row, col_custo_idx + 1, novo_custo_medio)
        logging.info(f"✅ Compra registrada e custo médio atualizado para o SKU {sku_alvo}.")
        return True, "Compra registrada e custo médio atualizado com sucesso!"
    except Exception as e:
        logging.error(f"❌ ERRO ao registrar compra para o SKU {sku_alvo}: {e}")
        return False, f"Ocorreu um erro: {e}"

