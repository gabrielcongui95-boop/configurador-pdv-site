import streamlit as st
import streamlit.components.v1 as components
import pymysql
import pandas as pd
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# Define o fuso horário oficial de Brasília (UTC-3)
FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Monitoramento PDV",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS para otimização visual no Celular e Espaçamento Reduzido nos Botões
st.markdown("""
    <style>
        /* Reduz o espaçamento entre elementos e botões na barra lateral */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {
            gap: 0.3rem !important;
        }
        [data-testid="stSidebar"] .stButton > button {
            width: 100% !important;
            margin-bottom: 2px !important;
        }
        
        /* Ajustes para telas pequenas (Celulares) */
        @media (max-width: 768px) {
            .stButton > button {
                width: 100% !important;
                height: 3em !important;
                font-size: 16px !important;
            }
            .block-container {
                padding-left: 0.8rem !important;
                padding-right: 0.8rem !important;
                padding-top: 1rem !important;
            }
        }
    </style>
""", unsafe_allow_html=True)

# --- CONFIGURAÇÃO DO BANCO ---
DB_HOST = st.secrets.get("DB_HOST", "mysql-71db31c-gabriel-8279.g.aivencloud.com")
DB_PORT = int(st.secrets.get("DB_PORT", 14801))
DB_USER = st.secrets.get("DB_USER", "avnadmin")
DB_PASS = st.secrets.get("DB_PASS", "AVNS_krbCrutmFqF_LkqTrsa")
DB_NAME = st.secrets.get("DB_NAME", "monitoramento_pdv")

def conectar_banco():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME,
        ssl={'ssl': True}, connect_timeout=5
    )

# --- FUNÇÕES DE BANCO ---
def buscar_dados_dashboard():
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute("SELECT NOW()")
            db_now = cursor.fetchone()[0]

            query = "SELECT nome_loja, rede, status, ultima_atualizacao, monitoramento_ativo, COALESCE(auto_restart, 0), comando FROM status_lojas ORDER BY rede ASC, nome_loja ASC"
            cursor.execute(query)
            dados = cursor.fetchall()
        
        lista_temp = []
        for row in dados:
            nome_loja, rede_nome, status_banco, ultima_att, m_ativo, a_restart, comando_banco = row
            
            delta_seconds = (db_now - ultima_att).total_seconds() if ultima_att else 999999

            if m_ativo == 0:
                status_calc = 'PAUSADO'
            elif delta_seconds > 75:
                status_calc = 'DESLIGADO'
            else:
                # REGRA: Converte erros ERR 401 e ERR 403 para ONLINE
                status_str = str(status_banco).upper() if status_banco else ""
                if any(err in status_str for err in ["401", "403", "ERR"]):
                    status_calc = 'ONLINE'
                else:
                    status_calc = status_banco

            if ultima_att:
                if ultima_att.tzinfo is None:
                    ultima_att_utc = ultima_att.replace(tzinfo=ZoneInfo("UTC"))
                else:
                    ultima_att_utc = ultima_att
                ultima_att_local = ultima_att_utc.astimezone(FUSO_BRASILIA).strftime('%d/%m/%Y %H:%M:%S')
            else:
                ultima_att_local = "-"

            # --- EXTRAÇÃO INTELIGENTE DA REDE (ANTES DA BARRA '/') ---
            raw_rede = str(rede_nome).strip() if rede_nome else ""
            raw_loja = str(nome_loja).strip() if nome_loja else ""

            # Extrai o código da Rede (ex: '927' de '927/12')
            if "/" in raw_rede:
                cod_rede = raw_rede.split("/")[0].strip()
            elif "/" in raw_loja:
                cod_rede = raw_loja.split("/")[0].strip()
            else:
                cod_rede = raw_rede if raw_rede else "Sem Rede"

            # Formata Rede/Loja para exibição (Ex: "927/12 - Loja teste")
            if raw_rede and raw_rede != "-":
                rede_loja_fmt = f"{raw_rede} - {nome_loja}"
            else:
                rede_loja_fmt = nome_loja

            lista_temp.append({
                "Rede/Loja": rede_loja_fmt,
                "Nome da Loja": nome_loja,
                "Rede": cod_rede,  # Código da rede isolado para agrupamento
                "Status": status_calc,
                "Auto Reinício": "✅ SIM" if a_restart == 1 else "❌ NÃO",
                "Última Atualização": ultima_att_local,
                "Comando Pendente": comando_banco or "-"
            })
        
        conn.close()
        return pd.DataFrame(lista_temp)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        return pd.DataFrame()

def executar_comando_remoto(lojas, comando):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            cursor.execute(f"UPDATE status_lojas SET comando = %s WHERE nome_loja IN ({format_strings})", (comando,) + tuple(lojas))
        conn.commit()
        conn.close()
        st.toast(f"Comando '{comando}' enviado para {len(lojas)} loja(s)!", icon="🚀")
    except Exception as e:
        st.error(f"Erro ao enviar comando: {e}")

def reiniciar_lojas(lojas):
    executar_comando_remoto(lojas, "STOP")
    st.toast("Comando STOP enviado! Aguardando 15 segundos para reabrir...", icon="⏳")
    with st.spinner("🔄 Encerrando o monitor... Aguardando 15 segundos para enviar o comando de reabrir (START)..."):
        time.sleep(15)
    executar_comando_remoto(lojas, "START")

def alterar_pausa(lojas, pausar):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            novo_m_ativo = 0 if pausar else 1
            novo_status = 'PAUSADO' if pausar else 'ONLINE'
            
            cursor.execute(f"UPDATE status_lojas SET monitoramento_ativo = %s, status = %s, ultima_atualizacao = NOW() WHERE nome_loja IN ({format_strings})", (novo_m_ativo, novo_status) + tuple(lojas))
        conn.commit()
        conn.close()
        st.toast("Status de monitoramento atualizado!", icon="🔄")
    except Exception as e:
        st.error(f"Erro na alteração de pausa: {e}")

def alterar_auto_restart(lojas, ativar):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            novo_auto_restart = 1 if ativar else 0
            cursor.execute(
                f"UPDATE status_lojas SET auto_restart = %s WHERE nome_loja IN ({format_strings})",
                (novo_auto_restart,) + tuple(lojas)
            )
        conn.commit()
        conn.close()
        st.toast("Auto reinício atualizado com sucesso!", icon="🔁")
    except Exception as e:
        st.error(f"Erro ao alterar auto reinício: {e}")

def excluir_lojas(lojas):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            cursor.execute(f"DELETE FROM historico_status WHERE nome_loja IN ({format_strings})", tuple(lojas))
            cursor.execute(f"DELETE FROM status_lojas WHERE nome_loja IN ({format_strings})", tuple(lojas))
        conn.commit()
        conn.close()
        st.toast("Lojas removidas com sucesso!", icon="🗑️")
    except Exception as e:
        st.error(f"Erro ao excluir lojas: {e}")

def buscar_historico(nome_loja, data_inicio=None, data_fim=None):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            query = "SELECT status, data_evento FROM historico_status WHERE nome_loja = %s"
            params = [nome_loja]
            
            if data_inicio and data_fim:
                query += " AND DATE(data_evento) BETWEEN %s AND %s"
                params.extend([data_inicio, data_fim])
            elif data_inicio:
                query += " AND DATE(data_evento) >= %s"
                params.append(data_inicio)
            elif data_fim:
                query += " AND DATE(data_evento) <= %s"
                params.append(data_fim)
                
            query += " ORDER BY data_evento ASC"  # Ordena em ordem cronológica
            cursor.execute(query, tuple(params))
            res = cursor.fetchall()
        conn.close()

        if not res:
            return pd.DataFrame()

        dados_formatados = []
        agora_br = datetime.now(FUSO_BRASILIA)

        for i in range(len(res)):
            status, data_evento = res[i]
            
            if isinstance(data_evento, datetime):
                if data_evento.tzinfo is None:
                    data_evento = data_evento.replace(tzinfo=ZoneInfo("UTC"))
                dt_inicio = data_evento.astimezone(FUSO_BRASILIA)
            else:
                dt_inicio = agora_br

            if i + 1 < len(res):
                data_prox = res[i + 1][1]
                if isinstance(data_prox, datetime):
                    if data_prox.tzinfo is None:
                        data_prox = data_prox.replace(tzinfo=ZoneInfo("UTC"))
                    dt_fim = data_prox.astimezone(FUSO_BRASILIA)
                else:
                    dt_fim = agora_br
                fim_data_str = dt_fim.strftime('%d/%m/%Y %H:%M:%S')
                fim_hora_str = dt_fim.strftime('%H:%M:%S')
            else:
                fim_data_str = "Em andamento"
                fim_hora_str = "Atual"

            inicio_data_str = dt_inicio.strftime('%d/%m/%Y %H:%M:%S')
            inicio_hora_str = dt_inicio.strftime('%H:%M:%S')

            st_upper = str(status).upper()
            if "ONLINE" in st_upper:
                status_com_cor = f"🟢 {status}"
            elif "OFFLINE" in st_upper:
                status_com_cor = f"🔴 {status}"
            elif "PAUSADO" in st_upper:
                status_com_cor = f"🔵 {status}"
            elif "DESLIGADO" in st_upper:
                status_com_cor = f"⚪ {status}"
            else:
                status_com_cor = f"🟡 {status}"

            periodo_formatado = f"{inicio_hora_str} até {fim_hora_str}"

            dados_formatados.append({
                "Status": status_com_cor,
                "Período Horário": periodo_formatado,
                "Início": inicio_data_str,
                "Término": fim_data_str
            })

        dados_formatados.reverse()
        return pd.DataFrame(dados_formatados)
    except Exception as e:
        st.error(f"Erro ao buscar histórico: {e}")
        return pd.DataFrame()

# --- HELPER DE RENDERIZAÇÃO DAS TABELAS DE CADA ABA ---
def renderizar_grid_lojas(df_subset, tab_key, agrupar_por_rede=False):
    if df_subset.empty:
        st.info("Nenhuma loja encontrada neste status.")
        return

    def destacar_status(val):
        if val == 'ONLINE': return 'background-color: #162A16; color: #00FFB2'
        if val == 'OFFLINE': return 'background-color: #2A1616; color: #F75A68'
        if val == 'PAUSADO': return 'background-color: #16202A; color: #4CC4FF'
        if val == 'DESLIGADO': return 'background-color: #202024; color: #8D8D99'
        return ''

    df_ordenado = df_subset.sort_values(by=["Rede", "Nome da Loja"]).reset_index(drop=True)

    if agrupar_por_rede:
        # Agrupa pela Rede (o que vem antes da '/') e inicia RECOLHIDO (expanded=False)
        grupos = df_ordenado.groupby("Rede", sort=False)
        for idx, (rede_codigo, df_grupo) in enumerate(grupos):
            with st.expander(f"🏢 Rede: {rede_codigo} ({len(df_grupo)} loja(s))", expanded=False):
                event = st.dataframe(
                    df_grupo.style.map(destacar_status, subset=['Status']),
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="multi-row",
                    key=f"tabela_lojas_{tab_key}_rede_{idx}"
                )

                state_key = f"last_sel_{tab_key}_rede_{idx}"
                cur_sel = event.selection.rows
                
                if state_key not in st.session_state:
                    st.session_state[state_key] = cur_sel
                elif st.session_state[state_key] != cur_sel:
                    st.session_state[state_key] = cur_sel
                    novas_selecionadas = df_grupo.iloc[cur_sel]["Nome da Loja"].tolist() if cur_sel else []
                    outras_lojas = [l for l in st.session_state.get("lojas_selecionadas", []) if l not in df_grupo["Nome da Loja"].tolist()]
                    st.session_state["lojas_selecionadas"] = outras_lojas + novas_selecionadas
                    st.rerun()
    else:
        event = st.dataframe(
            df_ordenado.style.map(destacar_status, subset=['Status']),
            use_container_width=True,
            hide_index=True,
            height=450,
            on_select="rerun",
            selection_mode="multi-row",
            key=f"tabela_lojas_{tab_key}"
        )

        state_key = f"last_sel_{tab_key}"
        cur_sel = event.selection.rows
        
        if state_key not in st.session_state:
            st.session_state[state_key] = cur_sel
        elif st.session_state[state_key] != cur_sel:
            st.session_state[state_key] = cur_sel
            novas_selecionadas = df_ordenado.iloc[cur_sel]["Nome da Loja"].tolist() if cur_sel else []
            if st.session_state.get("lojas_selecionadas") != novas_selecionadas:
                st.session_state["lojas_selecionadas"] = novas_selecionadas
                st.rerun()

# --- FRAGMENTO COM AUTO-REFRESH A CADA 15 SEGUNDOS ---
@st.fragment(run_every="15s")
def renderizar_tabela_dashboard():
    df_lojas = buscar_dados_dashboard()
    
    col_t, col_r = st.columns([3, 1])
    with col_t:
        agora = datetime.now(FUSO_BRASILIA).strftime("%H:%M:%S")
        st.caption(f"⚡ Atualização automática ativa (Última: {agora} - Brasília)")
    with col_r:
        if st.button("🔄 Atualizar Agora", use_container_width=True):
            st.rerun()

    col_busca, col_toggle = st.columns([3, 1])
    with col_busca:
        termo_busca = st.text_input(
            "🔍 Filtrar por Rede/Loja ou Nome:", 
            placeholder="Ex: 927/12, 999/1, Loja teste...",
            key="campo_busca_lojas"
        )
    with col_toggle:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        agrupar_rede = st.toggle("📂 Agrupar por Rede", value=False, key="toggle_agrupar_rede")

    # JavaScript para forçar a busca em tempo real
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const inputs = doc.querySelectorAll('div[data-testid="stTextInput"] input');
        inputs.forEach(input => {
            if (!input.dataset.liveSearch) {
                input.dataset.liveSearch = "true";
                input.addEventListener('input', () => {
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                });
            }
        });
        </script>
        """,
        height=0,
        width=0
    )

    if not df_lojas.empty:
        if termo_busca:
            df_exibicao = df_lojas[
                df_lojas["Nome da Loja"].astype(str).str.contains(termo_busca, case=False, na=False) |
                df_lojas["Rede"].astype(str).str.contains(termo_busca, case=False, na=False) |
                df_lojas["Rede/Loja"].astype(str).str.contains(termo_busca, case=False, na=False)
            ].reset_index(drop=True)
        else:
            df_exibicao = df_lojas.reset_index(drop=True)

        # ABAS DE NAVEGAÇÃO DE STATUS
        tab_online, tab_offline, tab_pausado, tab_desligado, tab_todas = st.tabs([
            "🟢 Online", 
            "🔴 Offline", 
            "⏸️ Pausadas", 
            "⚪ Desligadas",
            "📋 Todas"
        ])

        with tab_online:
            df_sub = df_exibicao[df_exibicao["Status"] == "ONLINE"].reset_index(drop=True)
            renderizar_grid_lojas(df_sub, "online", agrupar_por_rede=agrupar_rede)

        with tab_offline:
            df_sub = df_exibicao[df_exibicao["Status"] == "OFFLINE"].reset_index(drop=True)
            renderizar_grid_lojas(df_sub, "offline", agrupar_por_rede=agrupar_rede)

        with tab_pausado:
            df_sub = df_exibicao[df_exibicao["Status"] == "PAUSADO"].reset_index(drop=True)
            renderizar_grid_lojas(df_sub, "pausado", agrupar_por_rede=agrupar_rede)

        with tab_desligado:
            df_sub = df_exibicao[df_exibicao["Status"] == "DESLIGADO"].reset_index(drop=True)
            renderizar_grid_lojas(df_sub, "desligado", agrupar_por_rede=agrupar_rede)

        with tab_todas:
            renderizar_grid_lojas(df_exibicao, "todas", agrupar_por_rede=agrupar_rede)
            
    else:
        st.info("Nenhuma loja encontrada.")

# --- INTERFACE WEB PRINCIPAL ---
st.title("Lojas")

# Inicializa o estado global das lojas selecionadas
if "lojas_selecionadas" not in st.session_state:
    st.session_state["lojas_selecionadas"] = []

lojas_selecionadas = st.session_state["lojas_selecionadas"]
desabilitar_botoes = len(lojas_selecionadas) == 0

# --- BARRA LATERAL (PAINEL OPERACIONAL ADAPTADO) ---
st.sidebar.header("🖥️ PAINEL OPERACIONAL")

if lojas_selecionadas:
    st.sidebar.success(f"📌 {len(lojas_selecionadas)} loja(s) selecionada(s)")
else:
    st.sidebar.info("Selecione lojas para acionar os comandos.")

st.sidebar.markdown("---")

# 1. COMANDOS REMOTOS
st.sidebar.subheader("🕹️ Comandos Remotos")
col_cmd1, col_cmd2 = st.sidebar.columns(2)
with col_cmd1:
    if st.button("▶️ Iniciar", disabled=desabilitar_botoes, use_container_width=True, help="Iniciar Pedidos Web"):
        executar_comando_remoto(lojas_selecionadas, "START")
with col_cmd2:
    if st.button("🔄 Reiniciar", disabled=desabilitar_botoes, use_container_width=True, help="Reiniciar Pedidos Web"):
        reiniciar_lojas(lojas_selecionadas)

# 2. MONITORAMENTO E AUTO REINÍCIO
st.sidebar.subheader("⏸️ Monitoramento")
col_p1, col_p2 = st.sidebar.columns(2)
with col_p1:
    if st.button("⏸️ Pausar", disabled=desabilitar_botoes, use_container_width=True):
        alterar_pausa(lojas_selecionadas, True)
with col_p2:
    if st.button("▶️ Retomar", disabled=desabilitar_botoes, use_container_width=True):
        alterar_pausa(lojas_selecionadas, False)

st.sidebar.subheader("🔁 Auto Reinício")
col_ar1, col_ar2 = st.sidebar.columns(2)
with col_ar1:
    if st.button("✅ Ativar", disabled=desabilitar_botoes, use_container_width=True, key="btn_ar_ativar"):
        alterar_auto_restart(lojas_selecionadas, True)
with col_ar2:
    if st.button("❌ Desativar", disabled=desabilitar_botoes, use_container_width=True, key="btn_ar_desativar"):
        alterar_auto_restart(lojas_selecionadas, False)

st.sidebar.markdown("---")

# 3. MANUTENÇÃO E AÇÕES CRÍTICAS
st.sidebar.subheader("⚠️ Sistema & Manutenção")
if st.sidebar.button("🗑️ Remover Monitor (Uninstall)", disabled=desabilitar_botoes, use_container_width=True):
    executar_comando_remoto(lojas_selecionadas, "UNINSTALL")

if st.sidebar.button("🚨 Apagar Lojas do Banco", disabled=desabilitar_botoes, type="primary", use_container_width=True):
    excluir_lojas(lojas_selecionadas)
    st.session_state["lojas_selecionadas"] = []
    st.rerun()

# ABA PRINCIPAL DE NAVEGAÇÃO
tab_dash, tab_hist = st.tabs(["📊 Painel Geral", "📜 Logs"])

# ABA 1: DASHBOARD
with tab_dash:
    renderizar_tabela_dashboard()

# ABA 2: HISTÓRICO
with tab_hist:
    st.subheader("Histórico por Loja")
    
    df_lojas_menu = buscar_dados_dashboard()
    
    col_h1, col_h2 = st.columns([1, 1])
    with col_h1:
        if not df_lojas_menu.empty:
            opcoes_lojas = dict(zip(df_lojas_menu["Rede/Loja"], df_lojas_menu["Nome da Loja"]))
            loja_exibida = st.selectbox("Escolha a loja para ver o histórico:", list(opcoes_lojas.keys()))
            loja_hist_sel = opcoes_lojas.get(loja_exibida)
        else:
            loja_hist_sel = None
            st.info("Nenhuma loja cadastrada.")
            
    with col_h2:
        periodo = st.date_input("Filtrar por período (Início e Fim):", value=(), format="DD/MM/YYYY")

    data_ini = periodo[0] if len(periodo) > 0 else None
    data_fim = periodo[1] if len(periodo) > 1 else None

    if loja_hist_sel:
        df_hist = buscar_historico(loja_hist_sel, data_ini, data_fim)
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum histórico encontrado para o filtro selecionado.")
