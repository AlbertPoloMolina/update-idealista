import requests
import base64
import pandas as pd
import json
import os
from datetime import datetime
import geopandas as gpd
from shapely.geometry import Point

# ==== CREDENCIALES IDEALISTA ====
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# ==== CREDENCIALES TELEGRAM ====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Reemplaza con tu token del bot
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Reemplaza con tu ID de usuario

# ==== PARÁMETROS DE BÚSQUEDA ====
BASE_URL = 'https://api.idealista.com/3.5/'
COUNTRY = 'es'
LANGUAGE = 'es'
MAX_ITEMS = '50'
PROPERTY_TYPE = 'homes'
ORDER = 'priceDown'
CENTER = '39.825749,-0.232300'
DISTANCE = '5000'
SORT = 'desc'
CSV_PATH = "historial_idealista.csv"

# ==== FUNCIÓN PARA AUTENTICACIÓN ====
def get_access_token():
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    token_url = "https://api.idealista.com/oauth/token"
    data = {"grant_type": "client_credentials", "scope": "read"}
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }

    response = requests.post(token_url, data=data, headers=headers)
    response.raise_for_status()
    return response.json()["access_token"]

# ==== CONSTRUCCIÓN DE LA URL DE BÚSQUEDA ====
def define_search_url(operation, page):
    return (BASE_URL +
            COUNTRY +
            '/search?operation=' + operation +
            '&maxItems=' + MAX_ITEMS +
            '&order=' + ORDER +
            '&center=' + CENTER +
            '&distance=' + DISTANCE +
            '&propertyType=' + PROPERTY_TYPE +
            '&sort=' + SORT +
            f'&numPage={page}' +
            '&language=' + LANGUAGE)

# ==== REALIZA LA CONSULTA A LA API ====
def search_api(url, token):
    headers = {'Content-Type': "application/json", 'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return json.loads(response.text)

# ==== PROCESA LOS RESULTADOS A DATAFRAME ====
def results_to_df(results, operation):
    df = pd.DataFrame.from_dict(results['elementList'])
    df['operation'] = operation
    df['updateDate'] = datetime.now().strftime("%Y-%m-%d")
    return df

# ==== CONSULTA SOLO LA PRIMERA PÁGINA PARA UNA OPERACIÓN ====
def get_all_results(operation, token):
    """Consulta solo la primera página de resultados para evitar repeticiones"""
    page = 1
    url = define_search_url(operation, page)
    results = search_api(url, token)

    if 'elementList' not in results or not results['elementList']:
        print(f"⚠️  No se encontraron resultados para {operation}")
        return pd.DataFrame()

    df = results_to_df(results, operation)
    print(f"📄 Página {page}: {len(df)} propiedades encontradas para {operation}")
    
    return df

# ==== ACTUALIZA EL CSV HISTÓRICO ====
def update_csv(csv_path, new_data):
    if os.path.exists(csv_path):
        old_data = pd.read_csv(csv_path, header=0, encoding='utf-8')
        combined = pd.concat([old_data, new_data], ignore_index=True)
        combined.drop_duplicates(subset=["propertyCode", "updateDate"], inplace=True)
    else:
        combined = new_data
    combined.to_csv(csv_path, index=False, encoding='utf-8')
    return combined

# ==== FUNCIÓN PARA ENVIAR MENSAJES A TELEGRAM ====
def send_telegram_message(message):
    """Envía un mensaje a través del bot de Telegram"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "TU_TOKEN_AQUI":
        print("⚠️  Token de Telegram no configurado. No se enviará mensaje.")
        return False
    
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        print("⚠️  Chat ID de Telegram no configurado. No se enviará mensaje.")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        
        if response.json()["ok"]:
            print("✅ Mensaje enviado a Telegram exitosamente")
            return True
        else:
            print("❌ Error al enviar mensaje a Telegram")
            return False
            
    except Exception as e:
        print(f"❌ Error al enviar mensaje a Telegram: {e}")
        return False

# ==== FUNCIÓN PARA CREAR RESUMEN DE RESULTADOS ====
def create_summary_message(df_total, df_final, operation_type):
    """Crea un mensaje resumen para enviar a Telegram"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Estadísticas básicas
    total_new = len(df_total)
    total_accumulated = len(df_final)
    
    # Contar por tipo de operación
    rent_count = len(df_total[df_total['operation'] == 'rent']) if 'rent' in df_total['operation'].values else 0
    sale_count = len(df_total[df_total['operation'] == 'sale']) if 'sale' in df_total['operation'].values else 0
    
    # Precios promedio si están disponibles
    try:
        if 'price' in df_total.columns:
            avg_price_rent = df_total[df_total['operation'] == 'rent']['price'].mean() if rent_count > 0 else 0
            avg_price_sale = df_total[df_total['operation'] == 'sale']['price'].mean() if sale_count > 0 else 0
            price_info = f"\n💰 <b>Precios promedio:</b>\n   • Alquiler: {avg_price_rent:.0f}€\n   • Venta: {avg_price_sale:.0f}€"
        else:
            price_info = ""
    except:
        price_info = ""
    
    message = f"""
🏠 <b>Actualización Idealista Completada</b>
⏰ <b>Fecha:</b> {current_time}
📍 <b>Ubicación:</b> La Vall d'Uixó (5km radio)

📊 <b>Resumen de resultados:</b>
   • Nuevas propiedades: {total_new}
   • Alquiler: {rent_count}
   • Venta: {sale_count}
   • Total acumulado: {total_accumulated}{price_info}

✅ <b>Estado:</b> Archivo CSV actualizado correctamente
📁 <b>Ruta:</b> {CSV_PATH}
"""
    
    return message.strip()

# ==== EJECUCIÓN PRINCIPAL ====
if __name__ == "__main__":
    print("🚀 Iniciando actualización de Idealista...")
    
    try:
        print("🔑 Obteniendo token de acceso...")
        token = get_access_token()

        print("🏠 Consultando propiedades en alquiler...")
        df_rent = get_all_results("rent", token)

        print("🏠 Consultando propiedades en venta...")
        df_sale = get_all_results("sale", token)

        df_total = pd.concat([df_rent, df_sale], ignore_index=True)

        print(f"📈 Nuevas propiedades obtenidas: {len(df_total)}")

        df_final = update_csv(CSV_PATH, df_total)

        print(f"💾 Archivo actualizado: {CSV_PATH}")

                # === ASIGNAR CUSEC A VIVIENDAS SIN DISTRITO ===
        GEOJSON_PATH = "Lavall_wgs84.geojson"  # ruta a tu archivo GeoJSON

        if os.path.exists(GEOJSON_PATH):
            print("🗺️ Revisando viviendas sin CUSEC...")
            try:
                df_final = pd.read_csv(CSV_PATH)
                if 'CUSEC' not in df_final.columns:
                    df_final['CUSEC'] = None

                # Filtrar las que no tienen CUSEC
                sin_cusec = df_final[df_final['CUSEC'].isna() | (df_final['CUSEC'] == '')]

                if not sin_cusec.empty:
                    print(f"📍 {len(sin_cusec)} viviendas sin CUSEC. Calculando distritos...")

                    # Crear geometría con coordenadas
                    sin_cusec['geometry'] = sin_cusec.apply(
                        lambda r: Point(r['longitude'], r['latitude']), axis=1
                    )
                    gdf_sin_cusec = gpd.GeoDataFrame(sin_cusec, geometry='geometry', crs="EPSG:4326")

                    # Cargar distritos (solo CUSEC)
                    gdf_distritos = gpd.read_file(GEOJSON_PATH)[['CUSEC', 'geometry']]
                    if gdf_distritos.crs != gdf_sin_cusec.crs:
                        gdf_distritos = gdf_distritos.to_crs(gdf_sin_cusec.crs)

                    # Unión espacial solo para las viviendas sin CUSEC
                    gdf_asignadas = gpd.sjoin(gdf_sin_cusec, gdf_distritos, how="left", predicate="intersects")

                    # Actualizar valores de CUSEC en el DataFrame principal
                    df_final.set_index('propertyCode', inplace=True)
                    gdf_asignadas.set_index('propertyCode', inplace=True)
                    df_final.update(gdf_asignadas[['CUSEC']])
                    df_final.reset_index(inplace=True)

                    # Guardar CSV actualizado
                    df_final.to_csv(CSV_PATH, index=False, encoding='utf-8')
                    print("✅ CUSEC asignado y CSV actualizado.")
                else:
                    print("✅ Todas las viviendas ya tienen CUSEC.")
            except Exception as e:
                print(f"⚠️ Error al asignar CUSEC: {e}")
        else:
            print(f"⚠️ No se encontró el archivo GeoJSON en {GEOJSON_PATH}. No se asignará CUSEC.")

        print(f"📊 Total acumulado: {len(df_final)}")
        
        # Crear y enviar mensaje a Telegram
        print("📱 Enviando resumen a Telegram...")
        summary_message = create_summary_message(df_total, df_final, "completa")
        send_telegram_message(summary_message)
        
        print("🎉 Proceso completado exitosamente!")
        
    except Exception as e:
        error_message = f"❌ <b>Error en la actualización de Idealista:</b>\n\n{str(e)}"
        print(f"Error: {e}")
        send_telegram_message(error_message)
