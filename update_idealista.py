import os
import sys
import json
import time
import base64
import argparse
from datetime import datetime

import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point


class IdealistaQuotaError(Exception):
    """Excepción lanzada cuando se supera la cuota de la API o rate limit persistente."""
    pass


# ==== CREDENCIALES IDEALISTA ====
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# ==== CREDENCIALES TELEGRAM ====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ==== PARÁMETROS GENERALES Y SEGURIDAD ====
BASE_URL = 'https://api.idealista.com/3.5/'
COUNTRY = 'es'
LANGUAGE = 'es'
MAX_ITEMS = '50'
PROPERTY_TYPE = 'homes'
ORDER = 'priceDown'
SORT = 'desc'
REQUEST_DELAY = 1.2        # Pausa en segundos entre peticiones para respetar rate limit (1 req/s)
REQUEST_TIMEOUT = 25       # Timeout en segundos por petición HTTP
DEFAULT_MAX_PAGES = 5      # Límite por defecto de páginas por consulta para proteger cuota mensual

# ==== CONFIGURACIÓN DE UBICACIONES ====
LOCATIONS = {
    "vall": {
        "name": "La Vall d'Uixó (5km radio)",
        "center": "39.825749,-0.232300",
        "distance": "5000",
        "csv_path": "historial_idealista.csv",
        "geojson_path": "Lavall_wgs84.geojson",
    },
    "cordoba": {
        "name": "Córdoba (5km radio)",
        "center": "37.892375,-4.780324",
        "distance": "5000",
        "csv_path": "historial_idealista_cordoba.csv",
        "geojson_path": None,
    },
}


def get_access_token(session: requests.Session | None = None) -> str:
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    token_url = "https://api.idealista.com/oauth/token"
    data = {"grant_type": "client_credentials", "scope": "read"}
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }

    http_client = session if session is not None else requests
    response = http_client.post(token_url, data=data, headers=headers, timeout=REQUEST_TIMEOUT)
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


def search_api(url: str, token: str, session: requests.Session | None = None, max_retries: int = 3) -> dict:
    headers = {'Content-Type': "application/json", 'Authorization': 'Bearer ' + token}
    http_client = session if session is not None else requests

    for attempt in range(max_retries):
        try:
            response = http_client.post(url, headers=headers, timeout=REQUEST_TIMEOUT)
            
            if response.status_code == 429:
                wait_time = (attempt + 1) * 5
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", response.text[:200])
                except Exception:
                    error_msg = response.text[:200]

                print(f"   ⏳ Rate limit / Cuota detectado (HTTP 429: {error_msg}). Pausa de {wait_time}s ({attempt + 1}/{max_retries})...")
                
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    raise IdealistaQuotaError(f"HTTP 429 - Cuota mensual agotada o exceso de peticiones: {error_msg}")

            response.raise_for_status()
            return json.loads(response.text)
        except IdealistaQuotaError:
            raise
        except requests.exceptions.RequestException as req_err:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 3
                print(f"   ⚠️ Error de red ({req_err}). Reintentando en {wait_time}s ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise req_err

    response.raise_for_status()
    return json.loads(response.text)


def results_to_df(results: dict, operation: str) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(results.get('elementList', []))
    if df.empty:
        return df
    df['operation'] = operation
    df['updateDate'] = datetime.now().strftime("%Y-%m-%d")
    return df


def get_all_results(
    operation: str,
    token: str,
    center: str,
    distance: str,
    session: requests.Session | None = None,
    max_pages: int = DEFAULT_MAX_PAGES
) -> pd.DataFrame:
    page = 1
    all_dfs = []
    visited_pages = set()

    while True:
        # Salvaguarda 1: Límite duro contra bucles infinitos y protección de cuota
        if page > max_pages:
            print(f"   🛑 Límite de seguridad alcanzado ({max_pages} páginas) para '{operation}'. Deteniendo paginación.")
            break

        # Salvaguarda 2: Detección de ciclos de páginas repetidas
        if page in visited_pages:
            print(f"   🛑 Detección de ciclo de página repetida (pág. {page}). Deteniendo paginación.")
            break
        visited_pages.add(page)

        url = define_search_url(operation, page, center, distance)
        try:
            results = search_api(url, token, session=session)
        except IdealistaQuotaError:
            # Si se agotó la cuota, relanzar para detener todo el proceso inmediatamente
            raise
        except Exception as e:
            print(f"   ⚠️ Detenida la descarga en la página {page} para '{operation}' ({e}). Conservando datos descargados.")
            break

        if 'elementList' not in results or not results['elementList']:
            break

        df = results_to_df(results, operation)
        if not df.empty:
            all_dfs.append(df)

        try:
            total_pages = int(results.get('totalPages', 1))
            actual_page = int(results.get('actualPage', page))
        except (ValueError, TypeError):
            total_pages = 1
            actual_page = page

        if actual_page >= total_pages:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def update_csv(csv_path: str, new_data: pd.DataFrame) -> pd.DataFrame:
    if new_data.empty:
        if os.path.exists(csv_path):
            return pd.read_csv(csv_path, header=0, encoding='utf-8', low_memory=False)
        return pd.DataFrame()

    if os.path.exists(csv_path):
        old_data = pd.read_csv(csv_path, header=0, encoding='utf-8', low_memory=False)
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
        response = requests.post(url, data=data, timeout=REQUEST_TIMEOUT)
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
        return pd.read_csv(csv_path, low_memory=False) if os.path.exists(csv_path) else pd.DataFrame()

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No existe {csv_path}")
    df = pd.read_csv(csv_path, low_memory=False)
    if 'CUSEC' not in df.columns:
        df['CUSEC'] = None
    df['CUSEC'] = df['CUSEC'].astype(object)

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
        cusec_by_code = gdf_join.set_index('propertyCode')[cusec_dist_col].astype(str).to_dict()
        before = df['CUSEC'].notna().sum()
        df.loc[mask_missing, 'CUSEC'] = df.loc[mask_missing, 'propertyCode'].map(cusec_by_code).fillna(df.loc[mask_missing, 'CUSEC'])
        after = df['CUSEC'].notna().sum()
        assigned = after - before
        df.to_csv(csv_path, index=False, encoding='utf-8')
    else:
        print("❌ No se pudo identificar la columna de CUSEC tras el join.")

    return df


def process_location(
    location: dict,
    token: str,
    session: requests.Session | None = None,
    max_pages: int = DEFAULT_MAX_PAGES
) -> None:
    name = location["name"]
    center = location["center"]
    distance = location["distance"]
    csv_path = location["csv_path"]
    geojson_path = location.get("geojson_path")

    print(f"\n📍 Procesando ubicación: {name} (Centro: {center}, Radio: {int(distance)//1000}km)...")

    df_rent = get_all_results("rent", token, center, distance, session=session, max_pages=max_pages)
    print(f"   • Alquiler: {len(df_rent)} propiedades obtenidas")

    df_sale = get_all_results("sale", token, center, distance, session=session, max_pages=max_pages)
    print(f"   • Venta: {len(df_sale)} propiedades obtenidas")

    df_total = pd.concat([df_rent, df_sale], ignore_index=True)

    df_final = update_csv(csv_path, df_total)
    print(f"   • CSV actualizado en '{csv_path}' con {len(df_final)} filas acumuladas.")

    if geojson_path and not df_total.empty:
        df_final = assign_cusec_to_csv(csv_path, geojson_path)

    summary_message = create_summary_message(name, csv_path, df_total, df_final)
    send_telegram_message(summary_message)


def parse_args():
    default_loc = os.getenv("LOCATION", "all").lower()
    parser = argparse.ArgumentParser(description="Actualizador de Idealista multi-ubicación con protecciones anti-bucle y control de cuota.")
    parser.add_argument(
        "--location", "-l",
        choices=list(LOCATIONS.keys()) + ["all"],
        default=default_loc if default_loc in list(LOCATIONS.keys()) + ["all"] else "all",
        help="Ubicación a procesar: 'vall', 'cordoba' o 'all' (por defecto: all o variable de entorno LOCATION)."
    )
    parser.add_argument(
        "--max-pages", "-m",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Límite máximo de páginas por operación (por defecto: {DEFAULT_MAX_PAGES})."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target_locations = LOCATIONS.values() if args.location == "all" else [LOCATIONS[args.location]]

    print(f"🚀 Iniciando actualización de Idealista (Ubicación: '{args.location}', Límite máx. páginas: {args.max_pages})...")
    session = requests.Session()
    try:
        token = get_access_token(session=session)

        for loc in target_locations:
            try:
                process_location(loc, token, session=session, max_pages=args.max_pages)
            except IdealistaQuotaError as q_err:
                error_message = f"🚨 <b>Cuota de API Idealista agotada (HTTP 429):</b>\n\n{str(q_err)}"
                print(f"\n❌ Deteniendo ejecución por cuota de API agotada: {q_err}")
                try:
                    send_telegram_message(error_message)
                except Exception:
                    pass
                sys.exit(1)
            except Exception as loc_error:
                error_message = f"❌ <b>Error al procesar {loc['name']}:</b>\n\n{str(loc_error)}"
                print(f"Error en {loc['name']}: {loc_error}")
                try:
                    send_telegram_message(error_message)
                except Exception:
                    pass

    except IdealistaQuotaError as q_err:
        error_message = f"🚨 <b>Cuota de API Idealista agotada (HTTP 429):</b>\n\n{str(q_err)}"
        print(f"\n❌ Error de cuota: {q_err}")
        try:
            send_telegram_message(error_message)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        error_message = f"❌ <b>Error general en la actualización de Idealista:</b>\n\n{str(e)}"
        print(f"Error general: {e}")
        try:
            send_telegram_message(error_message)
        except Exception:
            pass
        sys.exit(1)
    finally:
        session.close()
