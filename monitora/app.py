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
    initial_sidebar_state="expanded"
)

# ==============================================================================
# --- INÍCIO USUÁRIO ADM PADRÃO (REMOVER APÓS CRIAR O PRIMEIRO ADM NO BANCO) ---
# ==============================================================================
USUARIO_ADM_PADRAO = "admin"
SENHA_ADM_PADRAO = "admin123"
# ==============================================================================
# --- FIM USUÁRIO ADM PADRÃO (APAGAR ATÉ AQUI) ---
# ==============================================================================

# --- CORREÇÃO DE CSS: CORTE DE LAYOUT E ROLAGEM ---
st.markdown("""
    <style>
        /* Correção para corte do container de rolagem */
        .main .block-container {
            max-width: 98% !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 1rem !important;
            padding-bottom: 5rem !important;
        }
        
        .st-key-btn_reset_tab_hidden { display: none !important; }

        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {
            gap: 0.3rem !important;
        }
        [data-testid="stSidebar"] .stButton > button {
            width: 100% !important;
            margin-bottom: 2px !important;
        }
        
        @media (max-width: 768px) {
            .stButton > button {
                width: 100% !important;
                height: 3em !important;
                font-size: 16px !important;
            }
        }
    </style>
""", unsafe_allow_html=True)

# --- BANCO DE DADOS ---
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

def criar_tabelas_autenticacao():
    """Cria tabelas de usuários e auditoria se não existirem."""
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    usuario VARCHAR(50) UNIQUE NOT NULL,
                    senha VARCHAR(100) NOT NULL,
                    nivel VARCHAR(20) NOT NULL DEFAULT 'COMUM',
                    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs_auditoria (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    usuario VARCHAR(50) NOT NULL,
                    acao VARCHAR(100) NOT NULL,
                    detalhes TEXT,
                    data_hora DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Erro ao inicializar tabelas de controle de acesso: {e}")

criar_tabelas_autenticacao()

def registrar_log_auditoria(usuario, acao, detalhes=""):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO logs_auditoria (usuario, acao, detalhes, data_hora) VALUES (%s, %s, %s, NOW())",
                (usuario, acao, detalhes)
            )
        conn.commit()
        conn.close()
    except Exception:
        pass

# --- AUTENTICAÇÃO ---
if "usuario_logado" not in st.session_state:
    st.session_state["usuario_logado"] = None
    st.session_state["nivel_acesso"] = None

def autenticar_usuario(user, password):
    # Checagem do usuário fallback hardcoded (se existente)
    try:
        if 'USUARIO_ADM_PADRAO' in globals() and user == USUARIO_ADM_PADRAO and password == SENHA_ADM_PADRAO:
            st.session_state["usuario_logado"] = user
            st.session_state["nivel_acesso"] = "ADM"
            registrar_log_auditoria(user, "LOGIN", "Login realizado via credencial inicial ADM")
            return True
    except NameError:
        pass

    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute("SELECT usuario, nivel FROM usuarios WHERE usuario = %s AND senha = %s", (user, password))
            res = cursor.fetchone()
            if res:
                st.session_state["usuario_logado"] = res[0]
                st.session_state["nivel_acesso"] = res[1]
                registrar_log_auditoria(res[0], "LOGIN", "Login realizado com sucesso")
                conn.close()
                return True
        conn.close()
    except Exception as e:
        st.error(f"Erro de autenticação: {e}")
    return False

# SCREEN DE LOGIN
if not st.session_state["usuario_logado"]:
    st.title("🔐 Autenticação de Acesso - Monitoramento PDV")
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        with st.form("form_login"):
            usuario_input = st.text_input("Usuário:")
            senha_input = st.text_input("Senha:", type="password")
            btn_entrar = st.form_submit_button("🚀 Entrar no Sistema", use_container_width=True)
            if btn_entrar:
                if autenticar_usuario(usuario_input, senha_input):
                    st.success("Acesso autorizado!")
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")
    st.stop()

# --- DADOS E FUNÇÕES DO DASHBOARD ---
def buscar_dados_dashboard():
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute("SELECT NOW()")
            db_now = cursor.fetchone()[0]

            query = """
                SELECT nome_loja, rede, loja, status, ultima_atualizacao, monitoramento_ativo, 
                       COALESCE(auto_restart, 0), comando, maquina 
                FROM status_lojas 
                ORDER BY rede ASC, nome_loja ASC
            """
            cursor.execute(query)
            dados = cursor.fetchall()
        
        lista_temp = []
        for row in dados:
            nome_loja, rede_cod, loja_cod, status_banco, ultima_att, m_ativo, a_restart, comando_banco, nome_maquina = row
            
            delta_seconds = (db_now - ultima_att).total_seconds() if ultima_att else 999999

            if m_ativo == 0:
                status_calc = 'PAUSADO'
            elif delta_seconds > 75:
                status_calc = 'DESLIGADO'
            else:
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

            # Trata Exibição de Rede/Loja com compatibilidade
            if rede_cod and loja_cod:
                cod_rede = str(rede_cod).strip()
                rede_loja_fmt = f"{rede_cod}/{loja_cod} - {nome_loja}"
            else:
                raw_rede = str(rede_cod).strip() if rede_cod else "Sem Rede"
                cod_rede = raw_rede.split("/")[0] if "/" in raw_rede else raw_rede
                rede_loja_fmt = f"{raw_rede} - {nome_loja}" if raw_rede != "Sem Rede" else nome_loja

            status_monitoramento = "Ativo" if m_ativo == 1 else "Suspenso"

            lista_temp.append({
                "Rede/Loja": rede_loja_fmt,
                "Nome da Loja": nome_loja,
                "Rede": cod_rede,
                "Rodando em": nome_maquina or "Desconhecido",
                "Status": status_calc,
                "Monitoramento": status_monitoramento,
                "Auto Reinício": "✅ SIM" if a_restart == 1 else "❌ NÃO",
                "Última Atualização": ultima_att_local,
                "Comando Pendente": comando_banco or "-"
            })
        
        conn.close()
        return pd.DataFrame(lista_temp)
    except Exception as e:
        st.error(f"Erro ao carregar dados do banco: {e}")
        return pd.DataFrame()

def executar_comando_remoto(lojas, comando):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            cursor.execute(f"UPDATE status_lojas SET comando = %s WHERE nome_loja IN ({format_strings})", (comando,) + tuple(lojas))
        conn.commit()
        conn.close()
        
        # Log de Auditoria
        usr = st.session_state["usuario_logado"]
        registrar_log_auditoria(usr, f"COMANDO_{comando}", f"Lojas afetadas: {', '.join(lojas)}")
        st.toast(f"Comando '{comando}' enviado com sucesso!", icon="🚀")
    except Exception as e:
        st.error(f"Erro ao enviar comando: {e}")

def reiniciar_lojas(lojas):
    executar_comando_remoto(lojas, "STOP")
    st.toast("Comando STOP enviado! Aguardando para reabrir...", icon="⏳")
    with st.spinner("🔄 Encerrando o monitor... Aguardando para enviar comando START..."):
        time.sleep(10)
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
        
        acao = "PAUSAR" if pausar else "ATIVAR"
        registrar_log_auditoria(st.session_state["usuario_logado"], f"MONITORAMENTO_{acao}", f"Lojas: {', '.join(lojas)}")
        st.toast("Status de monitoramento atualizado!", icon="🔄")
    except Exception as e:
        st.error(f"Erro na alteração de pausa: {e}")

def alterar_auto_restart(lojas, ativar):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            novo_auto_restart = 1 if ativar else 0
            cursor.execute(f"UPDATE status_lojas SET auto_restart = %s WHERE nome_loja IN ({format_strings})", (novo_auto_restart,) + tuple(lojas))
        conn.commit()
        conn.close()
        
        acao = "ATIVAR_AUTORESTART" if ativar else "DESATIVAR_AUTORESTART"
        registrar_log_auditoria(st.session_state["usuario_logado"], acao, f"Lojas: {', '.join(lojas)}")
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
            cursor.execute(f"DELETE FROM maquinas_lojas WHERE nome_loja IN ({format_strings})", tuple(lojas))
        conn.commit()
        conn.close()
        
        registrar_log_auditoria(st.session_state["usuario_logado"], "EXCLUIR_LOJAS", f"Lojas removidas: {', '.join(lojas)}")
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
                
            query += " ORDER BY data_evento ASC"
            cursor.execute(query, tuple(params))
            res = cursor.fetchall()
        conn.close()

        if not res: return pd.DataFrame()

        dados_formatados = []
        agora_br = datetime.now(FUSO_BRASILIA)

        for i in range(len(res)):
            status, data_evento = res[i]
            
            if isinstance(data_evento, datetime):
                dt_inicio = data_evento.replace(tzinfo=ZoneInfo("UTC")).astimezone(FUSO_BRASILIA) if data_evento.tzinfo is None else data_evento.astimezone(FUSO_BRASILIA)
            else:
                dt_inicio = agora_br

            if i + 1 < len(res):
                data_prox = res[i + 1][1]
                dt_fim = data_prox.replace(tzinfo=ZoneInfo("UTC")).astimezone(FUSO_BRASILIA) if isinstance(data_prox, datetime) and data_prox.tzinfo is None else agora_br
                fim_data_str = dt_fim.strftime('%d/%m/%Y %H:%M:%S')
                fim_hora_str = dt_fim.strftime('%H:%M:%S')
            else:
                fim_data_str = "Em andamento"
                fim_hora_str = "Atual"

            st_upper = str(status).upper()
            if "ONLINE" in st_upper: status_com_cor = f"🟢 {status}"
            elif "OFFLINE" in st_upper: status_com_cor = f"🔴 {status}"
            elif "PAUSADO" in st_upper: status_com_cor = f"🔵 {status}"
            else: status_com_cor = f"🟡 {status}"

            dados_formatados.append({
                "Status": status_com_cor,
                "Período Horário": f"{dt_inicio.strftime('%H:%M:%S')} até {fim_hora_str}",
                "Início": dt_inicio.strftime('%d/%m/%Y %H:%M:%S'),
                "Término": fim_data_str
            })

        dados_formatados.reverse()
        return pd.DataFrame(dados_formatados)
    except Exception as e:
        st.error(f"Erro ao buscar histórico: {e}")
        return pd.DataFrame()

# --- RENDERIZADOR DE TABELA DE LOJAS ---
def renderizar_grid_lojas(df_subset, tab_key):
    if df_subset.empty:
        st.info("Nenhuma loja encontrada neste status.")
        return

    def destacar_estilos(val):
        if val == 'ONLINE': return 'background-color: #162A16; color: #00FFB2'
        if val == 'OFFLINE': return 'background-color: #2A1616; color: #F75A68'
        if val == 'PAUSADO': return 'background-color: #16202A; color: #4CC4FF'
        if val == 'DESLIGADO': return 'background-color: #202024; color: #8D8D99'
        if val == 'Ativo': return 'color: #00FFB2; font-weight: bold'
        if val == 'Suspenso': return 'color: #F75A68; font-weight: bold'
        return ''

    df_ordenado = df_subset.sort_values(by=["Rede", "Nome da Loja"]).reset_index(drop=True)
    grupos = df_ordenado.groupby("Rede", sort=False)

    for idx, (rede_codigo, df_grupo) in enumerate(grupos):
        with st.expander(f"🏢 Rede: {rede_codigo} ({len(df_grupo)} loja(s))", expanded=False):
            event = st.dataframe(
                df_grupo.style.map(destacar_estilos, subset=['Status', 'Monitoramento']),
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
                
                # SELECIONA A LOJA PARA VISUALIZAÇÃO RÁPIDA DOS LOGS
                if cur_sel:
                    st.session_state["loja_direcionada_log"] = df_grupo.iloc[cur_sel[0]]["Nome da Loja"]
                st.rerun()

# --- FRAGMENTO DE REFRESH DO DASHBOARD ---
@st.fragment(run_every="15s")
def renderizar_tabela_dashboard():
    df_lojas = buscar_dados_dashboard()
    
    col_t, col_r = st.columns([3, 1])
    with col_t:
        agora = datetime.now(FUSO_BRASILIA).strftime("%H:%M:%S")
        st.caption(f"⚡ Atualização automática ativa ({agora}) | Usuário: **{st.session_state['usuario_logado']}** ({st.session_state['nivel_acesso']})")
    with col_r:
        if st.button("🔄 Atualizar Agora", use_container_width=True):
            st.rerun()

    termo_busca = st.text_input(
        "🔍 Filtrar por Rede/Loja ou Nome da Maquina:", 
        placeholder="Ex: 927/12, Loja Centro, DESKTOP-PDV...",
        key="campo_busca_lojas"
    )

    if not df_lojas.empty:
        if termo_busca:
            df_exibicao = df_lojas[
                df_lojas["Nome da Loja"].astype(str).str.contains(termo_busca, case=False, na=False) |
                df_lojas["Rede"].astype(str).str.contains(termo_busca, case=False, na=False) |
                df_lojas["Rodando em"].astype(str).str.contains(termo_busca, case=False, na=False)
            ].reset_index(drop=True)
        else:
            df_exibicao = df_lojas.reset_index(drop=True)

        tab_online, tab_offline, tab_pausado, tab_desligado, tab_todas = st.tabs([
            "🟢 Online", "🔴 Offline", "⏸️ Pausadas", "⚪ Desligadas", "📋 Todas"
        ])

        with tab_online: renderizar_grid_lojas(df_exibicao[df_exibicao["Status"] == "ONLINE"], "online")
        with tab_offline: renderizar_grid_lojas(df_exibicao[df_exibicao["Status"] == "OFFLINE"], "offline")
        with tab_pausado: renderizar_grid_lojas(df_exibicao[df_exibicao["Status"] == "PAUSADO"], "pausado")
        with tab_desligado: renderizar_grid_lojas(df_exibicao[df_exibicao["Status"] == "DESLIGADO"], "desligado")
        with tab_todas: renderizar_grid_lojas(df_exibicao, "todas")
    else:
        st.info("Nenhuma loja encontrada.")

# --- BARRA LATERAL (PAINEL OPERACIONAL E USUÁRIO) ---
st.sidebar.header(f"👤 {st.session_state['usuario_logado']}")
if st.sidebar.button("🚪 Sair (Logout)", use_container_width=True):
    registrar_log_auditoria(st.session_state['usuario_logado'], "LOGOUT", "Sessão encerrada")
    st.session_state["usuario_logado"] = None
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🖥️ PAINEL OPERACIONAL")

lojas_selecionadas = st.session_state.get("lojas_selecionadas", [])
if lojas_selecionadas:
    st.sidebar.success(f"📌 {len(lojas_selecionadas)} loja(s) selecionada(s)")
else:
    st.sidebar.info("Selecione lojas para acionar os comandos.")

desabilitar_geral = len(lojas_selecionadas) == 0

# 1. COMANDOS REMOTOS (INCLUINDO NOVOS COMANDOS)
st.sidebar.subheader("🕹️ Comandos Remotos")
col_cmd1, col_cmd2 = st.sidebar.columns(2)
with col_cmd1:
    if st.button("▶️ Iniciar", disabled=desabilitar_geral, use_container_width=True):
        executar_comando_remoto(lojas_selecionadas, "START")
with col_cmd2:
    if st.button("🔄 Reiniciar", disabled=desabilitar_geral, use_container_width=True):
        reiniciar_lojas(lojas_selecionadas)

col_cmd3, col_cmd4 = st.sidebar.columns(2)
with col_cmd3:
    if st.button("🛑 Encerrar Web", disabled=desabilitar_geral, use_container_width=True, help="Mata o processo do Pedidos WEB uma vez"):
        executar_comando_remoto(lojas_selecionadas, "ENCERRAR")
with col_cmd4:
    if st.button("🔒 Bloquear Web", disabled=desabilitar_geral, use_container_width=True, help="Mata o processo e impede a reabertura a cada 5s"):
        executar_comando_remoto(lojas_selecionadas, "BLOQUEAR")

# 2. MONITORAMENTO E AUTO REINÍCIO
st.sidebar.subheader("⏸️ Monitoramento")
col_p1, col_p2 = st.sidebar.columns(2)
with col_p1:
    if st.button("⏸️ Pausar", disabled=desabilitar_geral, use_container_width=True):
        alterar_pausa(lojas_selecionadas, True)
with col_p2:
    if st.button("▶️ Ativar", disabled=desabilitar_geral, use_container_width=True):
        alterar_pausa(lojas_selecionadas, False)

st.sidebar.subheader("🔁 Auto Reinício")
col_ar1, col_ar2 = st.sidebar.columns(2)
with col_ar1:
    if st.button("✅ Ativar", disabled=desabilitar_geral, use_container_width=True):
        alterar_auto_restart(lojas_selecionadas, True)
with col_ar2:
    if st.button("❌ Desativar", disabled=desabilitar_geral, use_container_width=True):
        alterar_auto_restart(lojas_selecionadas, False)

st.sidebar.markdown("---")

# 3. MANUTENÇÃO (APENAS PARA ADM)
if st.session_state["nivel_acesso"] == "ADM":
    st.sidebar.subheader("⚠️ Ações de Administração")
    if st.sidebar.button("🗑️ Remover Monitor (Uninstall)", disabled=desabilitar_geral, use_container_width=True):
        executar_comando_remoto(lojas_selecionadas, "UNINSTALL")

    if st.sidebar.button("🚨 Apagar Lojas do Banco", disabled=desabilitar_geral, type="primary", use_container_width=True):
        excluir_lojas(lojas_selecionadas)
        st.session_state["lojas_selecionadas"] = []
        st.rerun()

# --- ESTRUTURA DE ABAS PRINCIPAIS DA TELA ---
abas_principais = ["📊 Painel Geral", "📜 Logs de Operação"]
if st.session_state["nivel_acesso"] == "ADM":
    abas_principais.extend(["👥 Gerenciar Usuários", "🛡️ Logs de Auditoria"])

guias = st.tabs(abas_principais)

# TAB 1: PAINEL GERAL
with guias[0]:
    renderizar_tabela_dashboard()

# TAB 2: LOGS DAS LOJAS
with guias[1]:
    st.subheader("📜 Histórico e Logs de Operação das Lojas")
    
    loja_foco = st.session_state.get("loja_direcionada_log", None)
    if loja_foco:
        st.info(f"🎯 Exibindo histórico direcionado para a loja: **{loja_foco}**")

    df_lojas_menu = buscar_dados_dashboard()
    if not df_lojas_menu.empty:
        lista_lojas = df_lojas_menu["Nome da Loja"].unique().tolist()
        idx_padrao = lista_lojas.index(loja_foco) if loja_foco in lista_lojas else 0
        
        loja_selecionada_log = st.selectbox("Selecione a Loja para Visualizar o Histórico:", options=lista_lojas, index=idx_padrao)
        df_hist = buscar_historico(loja_selecionada_log)
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum histórico registrado para esta loja.")

# TAB 3: GERENCIAMENTO DE USUÁRIOS (APENAS ADM)
if st.session_state["nivel_acesso"] == "ADM" and len(guias) > 2:
    with guias[2]:
        st.subheader("👥 Gerenciamento de Usuários do Painel")
        
        with st.form("form_novo_usuario"):
            st.write("### Criar Novo Usuário")
            novo_usr = st.text_input("Nome do Usuário:")
            nova_pwd = st.text_input("Senha:", type="password")
            novo_nvl = st.selectbox("Nível de Acesso:", options=["COMUM", "ADM"])
            btn_criar_usr = st.form_submit_button("➕ Criar Usuário")
            
            if btn_criar_usr:
                if novo_usr and nova_pwd:
                    try:
                        conn = conectar_banco()
                        with conn.cursor() as cursor:
                            cursor.execute("INSERT INTO usuarios (usuario, senha, nivel) VALUES (%s, %s, %s)", (novo_usr, nova_pwd, novo_nvl))
                        conn.commit()
                        conn.close()
                        registrar_log_auditoria(st.session_state["usuario_logado"], "CRIAR_USUARIO", f"Usuário criado: {novo_usr} ({novo_nvl})")
                        st.success(f"Usuário {novo_usr} criado com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao criar usuário (Pode já existir): {e}")

        st.markdown("---")
        st.write("### Usuários Cadastrados")
        try:
            conn = conectar_banco()
            df_usrs = pd.read_sql("SELECT id, usuario, nivel, criado_em FROM usuarios", conn)
            conn.close()
            st.dataframe(df_usrs, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Erro ao listar usuários: {e}")

# TAB 4: LOGS DE AUDITORIA (APENAS ADM)
if st.session_state["nivel_acesso"] == "ADM" and len(guias) > 3:
    with guias[3]:
        st.subheader("🛡️ Logs de Auditoria do Sistema (Acessos e Comandos)")
        try:
            conn = conectar_banco()
            df_aud = pd.read_sql("SELECT usuario, acao, detalhes, data_hora FROM logs_auditoria ORDER BY data_hora DESC LIMIT 200", conn)
            conn.close()
            st.dataframe(df_aud, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Erro ao carregar auditoria: {e}")
