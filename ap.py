import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
import base64
import os
import hashlib
import time
import uuid

# ==============================================================================
# 1. CONFIGURAÇÃO DE CONEXÃO COM FALLBACK
# ==============================================================================

# Tentar importar psycopg2 com fallback
try:
    import psycopg2
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    st.error("psycopg2 não está disponível. Instale com: pip install psycopg2-binary")

@st.cache_resource
def init_connection():
    """Inicializa conexão com fallback"""
    try:
        if not PSYCOPG2_AVAILABLE:
            st.error("Biblioteca de banco de dados não disponível")
            return None
            
        # Usa st.connection para gerenciamento automático
        conn = st.connection("postgres", type="sql")
        
        # Testa a conexão
        with conn.session as s:
            s.execute("SELECT 1")
            
        st.sidebar.success("✅ Conectado ao banco de dados!")
        return conn
        
    except Exception as e:
        st.sidebar.error(f"❌ Erro na conexão: {str(e)[:100]}...")
        return None

def get_db_cursor():
    """Retorna cursor para operações DML/DDL"""
    try:
        if conn is None:
            return None, None
            
        conn_obj = conn.session
        cursor_obj = conn_obj.cursor()
        return conn_obj, cursor_obj
        
    except Exception as e:
        st.error(f"Erro ao obter cursor: {e}")
        return None, None

# ==============================================================================
# 2. INICIALIZAÇÃO DO BANCO (MESMO CÓDIGO ANTERIOR)
# ==============================================================================

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    """Inicialização do banco de dados"""
    if st.session_state.get('db_initialized', False):
        return
        
    conn_temp, c = get_db_cursor()
    if c is None:
        st.error("Não foi possível inicializar o banco de dados")
        return
        
    try:
        # Tabela de usuários
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, 
                username TEXT UNIQUE, 
                password TEXT, 
                role TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabela de respostas HPO
        c.execute('''
            CREATE TABLE IF NOT EXISTS responses (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                a1 INTEGER, a2 INTEGER, b1 INTEGER, b2 INTEGER,
                c1 INTEGER, c2 INTEGER, d1 INTEGER, d2 INTEGER,
                e1 INTEGER, e2 INTEGER, f1 INTEGER, f2 INTEGER,
                g1 INTEGER, g2 INTEGER,
                comentario TEXT,
                session_id TEXT
            )
        ''')
        
        # Tabela de respostas de Liderança
        c.execute('''
            CREATE TABLE IF NOT EXISTS lideranca_responses (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                question_id TEXT,
                response TEXT,
                response_time REAL
            )
        ''')
        
        # Usuários padrão
        default_users = [
            ('admin', hash_password('admin123'), 'administrador'),
            ('gestor', hash_password('gestor123'), 'gestor')
        ]
        
        for username, password, role in default_users:
            c.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (username) DO NOTHING
            ''', (username, password, role))
        
        conn_temp.commit()
        st.session_state.db_initialized = True
        st.sidebar.success("✅ Banco de dados inicializado!")
        
    except Exception as e:
        st.error(f"❌ Erro na inicialização do banco: {e}")
        if conn_temp:
            conn_temp.rollback()
    finally:
        if c:
            c.close()

# ==============================================================================
# 3. FUNÇÕES CRUD COM TRY/EXCEPT
# ==============================================================================

def check_login(username, password):
    """Verifica credenciais de login"""
    try:
        hashed_password = hash_password(password)
        query = "SELECT id, username, role FROM users WHERE username = %s AND password = %s"
        
        conn_temp, c = get_db_cursor()
        if c is None:
            return None
            
        c.execute(query, (username, hashed_password))
        result = c.fetchone()
        
        if result:
            user_data = {
                'id': result[0],
                'username': result[1], 
                'role': result[2]
            }
            c.close()
            return user_data
            
        c.close()
        return None
        
    except Exception as e:
        st.error(f"Erro no login: {e}")
        return None

@st.cache_data(ttl=300)
def load_hpo_responses():
    """Carrega respostas HPO"""
    try:
        df = conn.query("SELECT * FROM responses ORDER BY timestamp DESC")
        if 'comentario' not in df.columns:
            df['comentario'] = ''
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados HPO: {e}")
        return pd.DataFrame()

def save_hpo_response(responses, comentario=""):
    """Salva resposta HPO"""
    conn_temp, c = get_db_cursor()
    if c is None:
        return False
        
    try:
        session_id = str(uuid.uuid4())
        
        c.execute('''
            INSERT INTO responses 
            (a1, a2, b1, b2, c1, c2, d1, d2, e1, e2, f1, f2, g1, g2, comentario, session_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', tuple(responses) + (comentario, session_id))
        
        conn_temp.commit()
        load_hpo_responses.clear()
        return True
        
    except Exception as e:
        st.error(f"Erro ao salvar resposta HPO: {e}")
        if conn_temp:
            conn_temp.rollback()
        return False
    finally:
        if c:
            c.close()

# ==============================================================================
# 4. PÁGINAS SIMPLIFICADAS
# ==============================================================================

def login_page():
    """Página de login"""
    st.title("🔐 Login - Sistema de Inquéritos")
    
    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submit = st.form_submit_button("Entrar")
        
        if submit:
            if not username or not password:
                st.error("Por favor, preencha todos os campos")
                return
                
            user = check_login(username, password)
            if user:
                st.session_state.user = user
                st.session_state.logged_in = True
                st.success(f"Bem-vindo, {user['username']}!")
                st.rerun()
            else:
                st.error("Credenciais inválidas")

def survey_hpo_page():
    """Página do questionário HPO"""
    st.title("📊 Questionário HPO")
    
    st.markdown("""
    **Instruções:** Para cada afirmação, avalie de 1 a 5:
    - 1: Discordo totalmente
    - 2: Discordo
    - 3: Neutro
    - 4: Concordo
    - 5: Concordo totalmente
    """)
    
    with st.form("hpo_form"):
        st.subheader("A. Liderança e Gestão")
        a1 = st.slider("A1 - Os líderes comunicam eficazmente a visão da organização", 1, 5, 3)
        a2 = st.slider("A2 - Os gestores apoiam o desenvolvimento da equipa", 1, 5, 3)
        
        st.subheader("B. Processos e Eficiência")
        b1 = st.slider("B1 - Os processos são eficientes e bem definidos", 1, 5, 3)
        b2 = st.slider("B2 - Existe pouca burocracia desnecessária", 1, 5, 3)
        
        comentario = st.text_area("Comentários adicionais (opcional)")
        
        submitted = st.form_submit_button("Submeter Resposta")
        
        if submitted:
            responses = [a1, a2, b1, b2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3]  # Simplificado para teste
            if save_hpo_response(responses, comentario):
                st.success("✅ Resposta submetida com sucesso! Obrigado pela sua participação.")
            else:
                st.error("❌ Erro ao submeter resposta. Tente novamente.")

def main_app():
    """Aplicação principal após login"""
    st.sidebar.title("📊 Menu Principal")
    
    menu_options = ["Questionário HPO", "Relatórios"]
    
    choice = st.sidebar.selectbox("Navegação", menu_options)
    
    if st.sidebar.button("🚪 Sair"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 **{st.session_state.user['username']}**")
    st.sidebar.write(f"🎯 **{st.session_state.user['role']}**")
    
    if choice == "Questionário HPO":
        survey_hpo_page()
    elif choice == "Relatórios":
        st.title("📈 Relatórios")
        hpo_df = load_hpo_responses()
        if not hpo_df.empty:
            st.write(f"Total de respostas: {len(hpo_df)}")
            st.dataframe(hpo_df.head())
        else:
            st.info("Nenhum dado disponível")

def show_deploy_instructions():
    """Mostra instruções de deploy se não houver conexão"""
    st.title("🚀 Configuração do Sistema")
    
    st.error("""
    **Configuração do Banco de Dados Necessária**
    
    Para usar esta aplicação, configure as credenciais do Neon DB:
    """)
    
    st.markdown("""
    ### No Streamlit Cloud:
    1. Vá em **Settings → Secrets**
    2. Adicione:
    ```toml
    [postgres]
    host = "ep-seu-host.neon.tech"
    database = "neondb"
    user = "neondb_owner"
    password = "npg_FGCLtO73IZrh"
    port = 5432
    ```
    """)
    
    if st.button("🔄 Tentar Reconexão"):
        st.rerun()

# ==============================================================================
# 5. CONFIGURAÇÃO E INICIALIZAÇÃO
# ==============================================================================

st.set_page_config(
    page_title="v.Ferreira - Sistema de Inquéritos",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto"
)

# CSS simplificado
st.markdown("""
    <style>
    .main .block-container {
        padding-top: 2rem;
    }
    @media (max-width: 768px) {
        .main .block-container {
            padding: 1rem;
        }
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 6. EXECUÇÃO PRINCIPAL
# ==============================================================================

# Inicializa conexão
conn = init_connection()

# Se não há conexão, mostra instruções
if conn is None:
    show_deploy_instructions()
    st.stop()

# Inicializa banco de dados
init_db()

# Verifica autenticação
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# Routing principal
if not st.session_state.logged_in:
    login_page()
else:
    main_app()