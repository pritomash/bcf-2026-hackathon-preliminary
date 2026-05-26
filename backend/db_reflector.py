import psycopg2
import logging

logger = logging.getLogger(__name__)

def fetch_dynamic_schema(conn: psycopg2.extensions.connection) -> str:
    """
    Reflects the database structure dynamically:
    1. Extracts tables, columns, and data types.
    2. Extracts foreign key relationships to prevent join hallucinations.
    """
    # Query 1: Columns metadata
    columns_query = """
        SELECT 
            t.table_name, 
            c.column_name, 
            c.data_type
        FROM 
            information_schema.tables t
        JOIN 
            information_schema.columns c ON t.table_name = c.table_name
        WHERE 
            t.table_schema = 'public'
        ORDER BY 
            t.table_name, c.ordinal_position;
    """
    
    # Query 2: Foreign key relationships mapping
    fk_query = """
        SELECT
            tc.table_name AS source_table,
            kcu.column_name AS source_column,
            ccu.table_name AS target_table,
            ccu.column_name AS target_column
        FROM
            information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints AS rc
              ON tc.constraint_name = rc.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON rc.unique_constraint_name = ccu.constraint_name
              AND rc.unique_constraint_schema = ccu.table_schema
        WHERE 
            tc.constraint_type = 'FOREIGN KEY' 
            AND tc.table_schema = 'public';
    """
    
    try:
        with conn.cursor() as cur:
            # 1. Fetch Columns
            cur.execute(columns_query)
            column_rows = cur.fetchall()
            
            # 2. Fetch Foreign Keys
            cur.execute(fk_query)
            fk_rows = cur.fetchall()
            
        if not column_rows:
            return "Database schema is empty or inaccessible."
            
        # Group column definitions by table name
        schema_map = {}
        for table_name, column_name, data_type in column_rows:
            if table_name not in schema_map:
                schema_map[table_name] = []
            schema_map[table_name].append(f"  - {column_name} ({data_type})")
            
        # Construct layout string
        schema_text = "=== DYNAMIC DATABASE SCHEMA LAYOUT ===\n"
        for table_name, columns in schema_map.items():
            schema_text += f"Table: {table_name}\n"
            schema_text += "\n".join(columns) + "\n\n"
            
        # Append dynamic relationship maps if they exist
        schema_text += "=== TABLE RELATIONSHIPS (JOIN KEYS) ===\n"
        if fk_rows:
            for src_tbl, src_col, tgt_tbl, tgt_col in fk_rows:
                schema_text += f"- {src_tbl}.{src_col} references {tgt_tbl}.{tgt_col}\n"
        else:
            schema_text += "- No foreign key constraints explicitly declared.\n"
            
        return schema_text
        
    except Exception as e:
        logger.error(f"Failed to dynamically extract database metadata: {e}")
        return "Error tracking schema metadata."