import os
import json
import base64
from datetime import datetime

import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point


# ==== CREDENCIALES IDEALISTA ====
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# ==== CREDENCIALES TELEGRAM ====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
GEOJSON_PATH = "Lavall_wgs84.geojson"


def get_access_token() -> str:
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


def define_search_url(operation: str, page: int) -> str:
    return (
        BASE_URL
        + COUNTRY
        + '/search?operation=' + operation
        + '&maxItems=' + MAX_ITEMS
        + '&order=' + ORDER
        + '&center=' + CENTER
        + '&distance=' + DISTANCE
        + '&propertyType=' + PROPERTY_TYPE
        + '&sort=' + SORT
        + f'&numPage={page}'
        + '&language=' + LANGUAGE
    )


def search_api(url: str, token: str) -> dict:
    headers = {'Content-Type': "application/json", 'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return json.loads(response.text)


def results_to_df(results: dict, operation: str) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(results.get('elementList', []))
    if df.empty:
        return df
    df['operation'] = operation
    df['updateDate'] = datetime.now().strftime("%Y-%m-%d")
    return df


def get_all_results(operation: str, token: str) -> pd.DataFrame:
    page = 1
    url = define_search_url(operation, page)
    results = search_api(url, token)

    if 'elementList' not in results or not results['elementList']:
        print(f"⚠️  No se encontraron resultados para {operation}")
        return pd.DataFrame()

    df = results_to_df(results, operation)
    print(f"📄 Página {page}: {len(df)} propiedades encontradas para {operation}")
    return df


def update_csv(csv_path: str, new_data: pd.DataFrame) -> pd.DataFrame:
    if os.path.exists(csv_path):
        old_data = pd.read_csv(csv_path, header=0, encoding='utf-8')
        combined = pd.concat([old_data, new_data], ignore_index=True)
        combined.drop_duplicates(subset=["propertyCode", "updateDate"], inplace=True)
    else:
        combined = new_data
    combined.to_csv(csv_path, index=False, encoding='utf-8')
    return combined


def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️  Token de Telegram no configurado. No se enviará mensaje.")
        return False
    if not TELEGRAM_CHAT_ID:
        print("⚠️  Chat ID de Telegram no configurado. No se enviará mensaje.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, data=data)
        response.raise_for_status()
        ok = bool(response.json().get("ok"))
        print("✅ Mensaje enviado a Telegram exitosamente" if ok else "❌ Error al enviar mensaje a Telegram")
        return ok
    except Exception as e:
        print(f"❌ Error al enviar mensaje a Telegram: {e}")
        return False


def create_summary_message(df_total: pd.DataFrame, df_final: pd.DataFrame, operation_type: str) -> str:
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_new = len(df_total) if df_total is not None else 0
    total_accumulated = len(df_final) if df_final is not None else 0
    rent_count = len(df_total[df_total['operation'] == 'rent']) if (df_total is not None and 'operation' in df_total.columns) else 0
    sale_count = len(df_total[df_total['operation'] == 'sale']) if (df_total is not None and 'operation' in df_total.columns) else 0

    try:
        if df_total is not None and 'price' in df_total.columns:
            avg_price_rent = df_total[df_total['operation'] == 'rent']['price'].mean() if rent_count > 0 else 0
            avg_price_sale = df_total[df_total['operation'] == 'sale']['price'].mean() if sale_count > 0 else 0
            price_info = f"\n💰 <b>Precios promedio:</b>\n   • Alquiler: {avg_price_rent:.0f}€\n   • Venta: {avg_price_sale:.0f}€"
        else:
            price_info = ""
    except Exception:
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


def assign_cusec_to_csv(csv_path: str, geojson_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No existe {csv_path}")
    df = pd.read_csv(csv_path)
    if 'CUSEC' not in df.columns:
        df['CUSEC'] = None

    mask_missing = df['CUSEC'].isna() | (df['CUSEC'] == '')
    df_missing = df.loc[mask_missing].copy()
    if df_missing.empty:
        print("✅ Todas las viviendas ya tienen CUSEC.")
        return df

    if not {'latitude', 'longitude'}.issubset(df_missing.columns):
        print("❌ No hay columnas latitude/longitude en el CSV. No se puede asignar CUSEC.")
        return df

    df_missing = df_missing.dropna(subset=['latitude', 'longitude']).copy()
    if df_missing.empty:
        print("⚠️ No hay coordenadas válidas para asignar CUSEC.")
        return df

    df_missing['geometry'] = df_missing.apply(lambda r: Point(r['longitude'], r['latitude']), axis=1)
    gdf_props = gpd.GeoDataFrame(df_missing, geometry='geometry', crs="EPSG:4326")

    if not os.path.exists(geojson_path):
        print(f"⚠️ No se encontró el archivo GeoJSON en {geojson_path}. No se asignará CUSEC.")
        return df

    gdf_dist = gpd.read_file(geojson_path)
    if 'CUSEC' not in gdf_dist.columns:
        raise KeyError("La capa de distritos no contiene columna 'CUSEC'")
    gdf_dist = gdf_dist[['CUSEC', 'geometry']].copy()
    if gdf_dist.crs != gdf_props.crs:
        gdf_dist = gdf_dist.to_crs(gdf_props.crs)
    try:
        gdf_dist['geometry'] = gdf_dist['geometry'].buffer(0)
    except Exception:
        pass

    gdf_join = gpd.sjoin(gdf_props, gdf_dist, how='left', predicate='intersects', lsuffix='__prop', rsuffix='__dist')
    cusec_cols = [c for c in gdf_join.columns if c.startswith('CUSEC')]
    cusec_dist_col = next((c for c in cusec_cols if c.endswith('__dist')), ('CUSEC' if 'CUSEC' in gdf_join.columns else (cusec_cols[0] if cusec_cols else None)))

    if (cusec_dist_col is None) or gdf_join[cusec_dist_col].isna().all():
        gdf_join = gpd.sjoin(gdf_props, gdf_dist, how='left', predicate='within', lsuffix='__prop', rsuffix='__dist')
        cusec_cols = [c for c in gdf_join.columns if c.startswith('CUSEC')]
        cusec_dist_col = next((c for c in cusec_cols if c.endswith('__dist')), ('CUSEC' if 'CUSEC' in gdf_join.columns else (cusec_cols[0] if cusec_cols else None)))

    if cusec_dist_col and (cusec_dist_col in gdf_join.columns):
        cusec_by_code = gdf_join.set_index('propertyCode')[cusec_dist_col].to_dict()
        before = df['CUSEC'].notna().sum()
        df.loc[mask_missing, 'CUSEC'] = df.loc[mask_missing, 'propertyCode'].map(cusec_by_code).fillna(df.loc[mask_missing, 'CUSEC'])
        after = df['CUSEC'].notna().sum()
        assigned = after - before
        print(f"✅ CUSEC asignados: {assigned} | Cobertura total: {df['CUSEC'].notna().mean():.2%}")
        df.to_csv(csv_path, index=False, encoding='utf-8')
    else:
        print("❌ No se pudo identificar la columna de CUSEC tras el join.")

    return df


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

        print("🗺️ Revisando viviendas sin CUSEC...")
        df_final = assign_cusec_to_csv(CSV_PATH, GEOJSON_PATH)

        print(f"📊 Total acumulado: {len(df_final)}")
        print("📱 Enviando resumen a Telegram...")
        summary_message = create_summary_message(df_total, df_final, "completa")
        send_telegram_message(summary_message)
        print("🎉 Proceso completado exitosamente!")

    except Exception as e:
        error_message = f"❌ <b>Error en la actualización de Idealista:</b>\n\n{str(e)}"
        print(f"Error: {e}")
        try:
            send_telegram_message(error_message)
        except Exception:
            pass

