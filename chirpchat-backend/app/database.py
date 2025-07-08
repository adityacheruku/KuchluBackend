from supabase import create_client, Client
from app.config import settings

# Initialize Supabase client
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_ANON_KEY
)

# Admin client for server-side operations
supabase_admin: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_ROLE_KEY
)

# Database connection helper
class DatabaseManager:
    def __init__(self):
        self.client = supabase
        self.admin_client = supabase_admin
    
    async def execute_query(self, query: str, params: dict = None):
        """Execute raw SQL query"""
        return self.admin_client.rpc('execute_sql', {
            'query': query,
            'params': params or {}
        })
    
    def get_table(self, table_name: str):
        """Get table instance for CRUD operations"""
        return self.client.table(table_name)

db_manager = DatabaseManager()