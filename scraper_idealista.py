import os
import sys
import re
import json
import time
import random
import argparse
from datetime import datetime

from bs4 import BeautifulSoup
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import requests

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None


# ==== CREDENCIALES TELEGRAM ====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ==== CONFIGURACIÓN DE SCRAPING ====
DEFAULT_MAX_PAGES = 5
BASE_DOMAIN = "https://www.idealista.com"

# Cabeceras estándar para simular un navegador real
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# ==== CONFIGURACIÓN DE UBICACIONES ====
LOCATIONS = {
    "vall": {
        "name": "La Vall d'Uixó",
        "slug": "la-vall-d-uixo-castellon",
        "municipality": "La Vall d'Uixo",
        "province": "Castellón",
        "csv_path": "historial_idealista.csv",
        "geojson_path": "Lavall_wgs84.geojson",
    },
    "cordoba": {
        "name": "Córdoba",
        "slug": "cordoba-cordoba",
        "municipality": "Córdoba",
        "province": "Córdoba",
        "csv_path": "historial_idealista_cordoba.csv",
        "geojson_path": None,
    },
}


def build_page_url(slug: str, operation: str, page: int) -> str:
    """
    Construye la URL pública de búsqueda de Idealista.
    operation: 'rent' -> 'alquiler-viviendas', 'sale' -> 'venta-viviendas'
    """
    op_slug = "alquiler-viviendas" if operation == "rent" else "venta-viviendas"
    if page == 1:
        return f"{BASE_DOMAIN}/{op_slug}/{slug}/"
    return f"{BASE_DOMAIN}/{op_slug}/{slug}/pagina-{page}.htm"


def fetch_html(url: str, proxy: str | None = None) -> tuple[int, str]:
    """
    Realiza la petición HTTP usando curl_cffi para emular la huella TLS de Chrome.
    Si curl_cffi no está disponible, hace fallback a requests estándar.
    """
    proxies = {"http": proxy, "https": proxy} if proxy else None

    if cffi_requests is not None:
        try:
            response = cffi_requests.get(
                url,
                headers=BROWSER_HEADERS,
                impersonate="chrome124",
                proxies=proxies,
                timeout=25,
            )
            return response.status_code, response.text
        except Exception as e:
            print(f"   ⚠️ Error en curl_cffi: {e}")

    # Fallback con requests
    session = requests.Session()
    response = session.get(url, headers=BROWSER_HEADERS, proxies=proxies, timeout=25)
    return response.status_code, response.text


def parse_price(price_text: str) -> float | None:
    """Extrae el valor numérico del precio (ej. '550 €/mes' -> 550.0, '145.000 €' -> 145000.0)."""
    if not price_text:
        return None
    cleaned = re.sub(r"[^\d]", "", price_text)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def parse_property_card(article: BeautifulSoup, operation: str, loc_info: dict) -> dict | None:
    """Extrae todos los atributos estructurados de un elemento <article> de Idealista."""
    prop_code = article.get("data-adid")
    if not prop_code:
        # Intentar extraer del enlace
        link_elem = article.find("a", class_="item-link")
        if link_elem and link_elem.get("href"):
            match = re.search(r"/inmueble/(\d+)/", link_elem["href"])
            if match:
                prop_code = match.group(1)

    if not prop_code:
        return None

    # Título y enlace
    link_elem = article.find("a", class_="item-link")
    title = link_elem.get_text(strip=True) if link_elem else ""
    rel_url = link_elem["href"] if (link_elem and link_elem.get("href")) else f"/inmueble/{prop_code}/"
    full_url = rel_url if rel_url.startswith("http") else f"{BASE_DOMAIN}{rel_url}"

    # Precio
    price_elem = article.find("span", class_="item-price")
    price = parse_price(price_elem.get_text(strip=True)) if price_elem else None

    # Thumbnail
    img_elem = article.find("img")
    thumbnail = ""
    if img_elem:
        thumbnail = img_elem.get("data-ondemand-img") or img_elem.get("src") or ""

    # Descripción
    desc_elem = article.find("div", class_="item-description")
    description = desc_elem.get_text(strip=True) if desc_elem else ""

    # Detalles: habitaciones, metros, planta, ascensor
    details = [d.get_text(strip=True).lower() for d in article.find_all("span", class_="item-detail")]
    
    rooms = None
    size = None
    floor = None
    has_lift = None
    exterior = None
    has_parking = False

    for detail in details:
        # Habitaciones
        match_hab = re.search(r"(\d+)\s*hab", detail)
        if match_hab:
            rooms = int(match_hab.group(1))

        # Metros cuadrados
        match_size = re.search(r"(\d+)\s*m²", detail)
        if match_size:
            size = float(match_size.group(1))

        # Planta
        if "planta" in detail or "bajo" in detail or "entreplanta" in detail or "sótano" in detail:
            if "bajo" in detail:
                floor = "bj"
            elif "entreplanta" in detail:
                floor = "en"
            elif "sótano" in detail:
                floor = "ss"
            else:
                match_floor = re.search(r"planta\s*(\d+)", detail)
                if match_floor:
                    floor = str(match_floor.group(1))

        # Ascensor
        if "con ascensor" in detail:
            has_lift = True
        elif "sin ascensor" in detail:
            has_lift = False

        # Exterior / Interior
        if "exterior" in detail:
            exterior = True
        elif "interior" in detail:
            exterior = False

        # Parking
        if "garaje" in detail or "parking" in detail:
            has_parking = True

    # Tipo de propiedad deducido del título
    lower_title = title.lower()
    if "piso" in lower_title or "apartamento" in lower_title:
        property_type = "flat"
    elif "chalet" in lower_title or "casa" in lower_title:
        property_type = "chalet"
    elif "ático" in lower_title or "atico" in lower_title:
        property_type = "penthouse"
    elif "dúplex" in lower_title or "duplex" in lower_title:
        property_type = "duplex"
    elif "estudio" in lower_title:
        property_type = "studio"
    else:
        property_type = "homes"

    today_str = datetime.now().strftime("%Y-%m-%d")

    return {
        "propertyCode": str(prop_code),
        "thumbnail": thumbnail,
        "externalReference": None,
        "numPhotos": 0,
        "floor": floor,
        "price": price,
        "priceInfo": f"{{'price': {{'amount': {price}}}}}" if price else None,
        "propertyType": property_type,
        "operation": operation,
        "size": size,
        "exterior": exterior,
        "rooms": rooms,
        "bathrooms": 1,
        "address": title,
        "province": loc_info.get("province"),
        "municipality": loc_info.get("municipality"),
        "country": "es",
        "latitude": None,
        "longitude": None,
        "showAddress": True,
        "url": full_url,
        "distance": 0,
        "description": description,
        "hasVideo": False,
        "status": "good",
        "newDevelopment": False,
        "hasLift": has_lift,
        "parkingSpace": has_parking,
        "updateDate": today_str,
    }


def parse_page_items(html: str, operation: str, loc_info: dict) -> list[dict]:
    """Parsea el HTML de la página y extrae todos los anuncios."""
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Buscar todos los artículos de inmuebles
    articles = soup.find_all("article", class_=lambda c: c and "item" in c.split())
    if not articles:
        articles = soup.find_all("article", attrs={"data-adid": True})
    if not articles:
        articles = soup.find_all("div", attrs={"data-adid": True})

    items = []
    for art in articles:
        prop = parse_property_card(art, operation, loc_info)
        if prop and prop.get("propertyCode"):
            items.append(prop)

    # 2. Si no se encontraron artículos por HTML, intentar extraer JSON-LD estructurado
    if not items:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    for elem in data.get("itemListElement", []):
                        item_data = elem.get("item", {})
                        if isinstance(item_data, dict) and "name" in item_data:
                            url = item_data.get("url", "")
                            match_code = re.search(r"/inmueble/(\d+)/", url)
                            if match_code:
                                code = match_code.group(1)
                                price = None
                                offers = item_data.get("offers", {})
                                if isinstance(offers, dict):
                                    price = float(offers.get("price", 0)) or None

                                items.append({
                                    "propertyCode": str(code),
                                    "thumbnail": item_data.get("image", ""),
                                    "externalReference": None,
                                    "numPhotos": 0,
                                    "floor": None,
                                    "price": price,
                                    "priceInfo": f"{{'price': {{'amount': {price}}}}}" if price else None,
                                    "propertyType": "homes",
                                    "operation": operation,
                                    "size": None,
                                    "exterior": None,
                                    "rooms": None,
                                    "bathrooms": 1,
                                    "address": item_data.get("name", ""),
                                    "province": loc_info.get("province"),
                                    "municipality": loc_info.get("municipality"),
                                    "country": "es",
                                    "latitude": None,
                                    "longitude": None,
                                    "showAddress": True,
                                    "url": url,
                                    "distance": 0,
                                    "description": item_data.get("description", ""),
                                    "hasVideo": False,
                                    "status": "good",
                                    "newDevelopment": False,
                                    "hasLift": None,
                                    "parkingSpace": False,
                                    "updateDate": datetime.now().strftime("%Y-%m-%d"),
                                })
            except Exception:
                pass

    return items


def scrape_location_operation(
    loc_info: dict,
    operation: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    proxy: str | None = None
) -> pd.DataFrame:
    slug = loc_info["slug"]
    all_items = []
    visited_codes = set()

    for page in range(1, max_pages + 1):
        url = build_page_url(slug, operation, page)
        print(f"   🌐 Consultando {operation} página {page}/{max_pages}: {url}")

        status_code, html = fetch_html(url, proxy=proxy)

        # Detección de bloqueos anti-bot (DataDome / Cloudflare)
        if status_code in (403, 429) or "datadome" in html.lower() or "challenge-running" in html.lower() or "geo.captcha" in html.lower():
            print(f"   🚨 Bloqueo anti-bot detectado (HTTP {status_code}). DataDome/Cloudflare interceptó la petición para '{operation}'.")
            print("   💡 Se recomienda usar un proxy residencial español (--proxy http://...) si ejecutas desde GitHub Actions.")
            break

        if status_code != 200:
            print(f"   ⚠️ Respuesta inesperada: HTTP {status_code} para '{operation}'. Deteniendo paginación.")
            break

        items = parse_page_items(html, operation, loc_info)
        if not items:
            print(f"   ℹ️ No se encontraron más anuncios en la página {page} para '{operation}'.")
            break

        new_items = 0
        for item in items:
            code = item["propertyCode"]
            if code not in visited_codes:
                visited_codes.add(code)
                all_items.append(item)
                new_items += 1

        print(f"      -> {new_items} inmuebles extraídos (Total en {operation}: {len(all_items)})")

        # Comprobar si hay botón 'siguiente' en la paginación
        soup = BeautifulSoup(html, "html.parser")
        next_button = soup.find("li", class_="next") or soup.find("a", class_="icon-arrow-right-after")
        if not next_button:
            print(f"   ℹ️ Última página de {operation} alcanzada.")
            break

        # Pausa aleatoria entre peticiones para emular comportamiento humano
        delay = random.uniform(3.0, 6.0)
        time.sleep(delay)

    if not all_items:
        return pd.DataFrame()

    return pd.DataFrame(all_items)


def update_csv(csv_path: str, new_data: pd.DataFrame) -> pd.DataFrame:
    if new_data.empty:
        if os.path.exists(csv_path):
            return pd.read_csv(csv_path, header=0, encoding='utf-8', low_memory=False)
        return pd.DataFrame()

    if os.path.exists(csv_path):
        old_data = pd.read_csv(csv_path, header=0, encoding='utf-8', low_memory=False)
        # Asegurar compatibilidad de tipos para evitar FutureWarning
        for col in new_data.columns:
            if col in old_data.columns:
                try:
                    new_data[col] = new_data[col].astype(old_data[col].dtype)
                except Exception:
                    pass
        combined = pd.concat([old_data, new_data], ignore_index=True)
        combined.drop_duplicates(subset=["propertyCode", "updateDate"], inplace=True)
    else:
        combined = new_data

    combined.to_csv(csv_path, index=False, encoding='utf-8')
    return combined


def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, data=data, timeout=25)
        response.raise_for_status()
        return bool(response.json().get("ok"))
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
🕷️ <b>Scraping Idealista Completado</b>
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
    if not geojson_path or not os.path.exists(geojson_path) or not os.path.exists(csv_path):
        return pd.read_csv(csv_path, low_memory=False) if os.path.exists(csv_path) else pd.DataFrame()

    df = pd.read_csv(csv_path, low_memory=False)
    if not {'latitude', 'longitude'}.issubset(df.columns):
        return df

    if 'CUSEC' not in df.columns:
        df['CUSEC'] = None

    # Solo intentar si hay coordenadas válidas no nulas
    mask_missing = df['CUSEC'].isna() | (df['CUSEC'] == '')
    df_missing = df.loc[mask_missing]
    if df_missing.empty:
        return df

    df_valid_coords = df_missing.dropna(subset=['latitude', 'longitude']).copy()
    if df_valid_coords.empty:
        return df

    df_valid_coords['geometry'] = df_valid_coords.apply(lambda r: Point(r['longitude'], r['latitude']), axis=1)
    gdf_props = gpd.GeoDataFrame(df_valid_coords, geometry='geometry', crs="EPSG:4326")

    gdf_dist = gpd.read_file(geojson_path)
    if 'CUSEC' not in gdf_dist.columns:
        return df

    gdf_dist = gdf_dist[['CUSEC', 'geometry']].copy()
    if gdf_dist.crs != gdf_props.crs:
        gdf_dist = gdf_dist.to_crs(gdf_props.crs)

    gdf_join = gpd.sjoin(gdf_props, gdf_dist, how='left', predicate='intersects')
    if 'CUSEC_right' in gdf_join.columns:
        cusec_map = gdf_join.set_index('propertyCode')['CUSEC_right'].dropna().astype(str).to_dict()
        if cusec_map:
            df['CUSEC'] = df['CUSEC'].astype(object)
            df.loc[mask_missing, 'CUSEC'] = df.loc[mask_missing, 'propertyCode'].map(cusec_map).fillna(df.loc[mask_missing, 'CUSEC'])
            df.to_csv(csv_path, index=False, encoding='utf-8')

    return df


def process_location(
    location: dict,
    operation: str = "all",
    max_pages: int = DEFAULT_MAX_PAGES,
    proxy: str | None = None
) -> None:
    name = location["name"]
    csv_path = location["csv_path"]
    geojson_path = location.get("geojson_path")

    print(f"\n📍 Procesando ubicación vía Web Scraping: {name} (Operación: {operation})...")

    dfs_to_combine = []

    if operation in ("rent", "all"):
        df_rent = scrape_location_operation(location, "rent", max_pages=max_pages, proxy=proxy)
        print(f"   • Alquiler: {len(df_rent)} propiedades obtenidas")
        if not df_rent.empty:
            dfs_to_combine.append(df_rent)

    if operation == "all":
        # Pausa de cortesía entre operaciones
        time.sleep(random.uniform(4.0, 7.0))

    if operation in ("sale", "all"):
        df_sale = scrape_location_operation(location, "sale", max_pages=max_pages, proxy=proxy)
        print(f"   • Venta: {len(df_sale)} propiedades obtenidas")
        if not df_sale.empty:
            dfs_to_combine.append(df_sale)

    df_total = pd.concat(dfs_to_combine, ignore_index=True) if dfs_to_combine else pd.DataFrame()
    df_final = update_csv(csv_path, df_total)
    print(f"   • CSV actualizado en '{csv_path}' con {len(df_final)} filas acumuladas.")

    if geojson_path and not df_total.empty:
        df_final = assign_cusec_to_csv(csv_path, geojson_path)

    summary_message = create_summary_message(name, csv_path, df_total, df_final)
    send_telegram_message(summary_message)


def parse_args():
    parser = argparse.ArgumentParser(description="Scraper alternativo de Idealista para obtención de viviendas sin límites de API.")
    parser.add_argument(
        "--location", "-l",
        choices=list(LOCATIONS.keys()) + ["all"],
        default="all",
        help="Ubicación a procesar: 'vall', 'cordoba' o 'all' (por defecto: all)."
    )
    parser.add_argument(
        "--operation", "-o",
        choices=["all", "rent", "sale"],
        default="all",
        help="Tipo de operación a procesar: 'rent', 'sale' o 'all' (por defecto: all)."
    )
    parser.add_argument(
        "--max-pages", "-m",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Límite máximo de páginas por operación (por defecto: {DEFAULT_MAX_PAGES})."
    )
    parser.add_argument(
        "--proxy", "-p",
        type=str,
        default=os.getenv("PROXY_URL"),
        help="URL de proxy residencial opcional (ej: http://user:pass@host:port)."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target_locations = LOCATIONS.values() if args.location == "all" else [LOCATIONS[args.location]]

    print(f"🚀 Iniciando Web Scraping de Idealista (Ubicación: '{args.location}', Operación: '{args.operation}', Límite máx. páginas: {args.max_pages})...")
    
    for loc in target_locations:
        try:
            process_location(loc, operation=args.operation, max_pages=args.max_pages, proxy=args.proxy)
        except Exception as e:
            error_message = f"❌ <b>Error en Scraping para {loc['name']}:</b>\n\n{str(e)}"
            print(f"Error: {e}")
            try:
                send_telegram_message(error_message)
            except Exception:
                pass
