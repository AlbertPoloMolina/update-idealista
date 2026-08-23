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

# ==== PARÁMETROS GENERALES ====
BASE_URL = 'https://api.idealista.com/3.5/'
COUNTRY = 'es'
LANGUAGE = 'es'
MAX_ITEMS = '50'
PROPERTY_TYPE = 'homes'
ORDER = 'priceDown'
SORT = 'desc'

# ==== CONFIGURACIÓN DE UBICACIONES ====
LOCATIONS = [
    {
        "name": "La Vall d'Uixó (5km radio)",
        "center": "39.825749,-0.232300",
        "distance": "5000",
        "csv_path": "historial_idealista.csv",
        "geojson_path": "Lavall_wgs84.geojson",
    },
    {
        "name": "Córdoba (20km radio)",
        "center": "37.892375,-4.780324",
        "distance": "20000",
        "csv_path": "historial_idealista_cordoba.csv",
        "geojson_path": None,
    },
]


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


def define_search_url(operation: str, page: int, center: str, distance: str) -> str:
    return (
        BASE_URL
        + COUNTRY
        + '/search?operation=' + operation
        + '&maxItems=' + MAX_ITEMS
        + '&order=' + ORDER
        + '&center=' + center
        + '&distance=' + distance
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


def get_all_results(operation: str, token: str, center: str, distance: str) -> pd.DataFrame:
    page = 1
    all_dfs = []

    while True:
        url = define_search_url(operation, page, center, distance)
        results = search_api(url, token)

        if 'elementList' not in results or not results['elementList']:
            break

        df = results_to_df(results, operation)
        if not df.empty:
            all_dfs.append(df)

        total_pages = int(results.get('totalPages', 1))
        actual_page = int(results.get('actualPage', page))

        if actual_page >= total_pages:
            break

        page += 1

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def update_csv(csv_path: str, new_data: pd.DataFrame) -> pd.DataFrame:
    if new_data.empty:
        if os.path.exists(csv_path):
            return pd.read_csv(csv_path, header=0, encoding='utf-8')
        return pd.DataFrame()

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
        return False
    if not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, data=data)
        response.raise_for_status()
        ok = bool(response.json().get("ok"))
        return ok
    except Exception as e:
        print(f"❌ Error al enviar mensaje a Telegram: {e}")
        return False


def create_summary_message(location_name: str, csv_path: str, df_total: pd.DataFrame, df_final: pd.DataFrame) -> str:
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
📍 <b>Ubicación:</b> {location_name}

📊 <b>Resumen de resultados:</b>
   • Nuevas propiedades: {total_new}
   • Alquiler: {rent_count}
   • Venta: {sale_count}
   • Total acumulado: {total_accumulated}{price_info}

✅ <b>Estado:</b> Archivo CSV actualizado correctamente
📁 <b>Ruta:</b> {csv_path}
"""
    return message.strip()


def assign_cusec_to_csv(csv_path: str, geojson_path: str | None) -> pd.DataFrame:
    if not geojson_path or not os.path.exists(geojson_path):
        return pd.read_csv(csv_path) if os.path.exists(csv_path) else pd.DataFrame()

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No existe {csv_path}")
    df = pd.read_csv(csv_path)
    if 'CUSEC' not in df.columns:
        df['CUSEC'] = None

    mask_missing = df['CUSEC'].isna() | (df['CUSEC'] == '')
    df_missing = df.loc[mask_missing].copy()
    if df_missing.empty:
        return df

    if not {'latitude', 'longitude'}.issubset(df_missing.columns):
        return df

    df_missing = df_missing.dropna(subset=['latitude', 'longitude']).copy()
    if df_missing.empty:
        return df

    df_missing['geometry'] = df_missing.apply(lambda r: Point(r['longitude'], r['latitude']), axis=1)
    gdf_props = gpd.GeoDataFrame(df_missing, geometry='geometry', crs="EPSG:4326")

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
        df.to_csv(csv_path, index=False, encoding='utf-8')
    else:
        print("❌ No se pudo identificar la columna de CUSEC tras el join.")

    return df


def process_location(location: dict, token: str) -> None:
    name = location["name"]
    center = location["center"]
    distance = location["distance"]
    csv_path = location["csv_path"]
    geojson_path = location.get("geojson_path")

    print(f"\n📍 Procesando ubicación: {name} (Centro: {center}, Radio: {int(distance)//1000}km)...")

    df_rent = get_all_results("rent", token, center, distance)
    print(f"   • Alquiler: {len(df_rent)} propiedades obtenidas")

    df_sale = get_all_results("sale", token, center, distance)
    print(f"   • Venta: {len(df_sale)} propiedades obtenidas")

    df_total = pd.concat([df_rent, df_sale], ignore_index=True)

    df_final = update_csv(csv_path, df_total)
    print(f"   • CSV actualizado en '{csv_path}' con {len(df_final)} filas acumuladas.")

    if geojson_path:
        df_final = assign_cusec_to_csv(csv_path, geojson_path)

    summary_message = create_summary_message(name, csv_path, df_total, df_final)
    send_telegram_message(summary_message)


if __name__ == "__main__":
    print("🚀 Iniciando actualización de Idealista...")
    try:
        token = get_access_token()

        for loc in LOCATIONS:
            try:
                process_location(loc, token)
            except Exception as loc_error:
                error_message = f"❌ <b>Error al procesar {loc['name']}:</b>\n\n{str(loc_error)}"
                print(f"Error en {loc['name']}: {loc_error}")
                try:
                    send_telegram_message(error_message)
                except Exception:
                    pass

    except Exception as e:
        error_message = f"❌ <b>Error general en la actualización de Idealista:</b>\n\n{str(e)}"
        print(f"Error general: {e}")
        try:
            send_telegram_message(error_message)
        except Exception:
            pass
