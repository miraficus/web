import urllib.request
import urllib.error
import re
import json
import xml.etree.ElementTree as ET
import sys
import ssl
import os
import csv
import io

GARLICSAVES_CSV_URL = "https://www.garlicsaves.com/tools/entitlements/csv?platform=ps5"
GITHUB_TSV_URL = "https://raw.githubusercontent.com/1jtp8sobiu/ps5-pkg/master/PS5_XML.tsv"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def parse_system_ver(system_ver_str):
    """Převede číslování Sony (např. 0x06000000 nebo dekadicky) na reálnou verzi PS5 FW"""
    try:
        val = int(system_ver_str)
        major = (val >> 24) & 0xFF
        minor = (val >> 16) & 0xFF

        if major > 13 or major == 0:
            return "01.00", 1.0

        formatted_str = f"{major:02d}.{minor:02d}"
        formatted_float = float(f"{major}.{minor}")
        return formatted_str, formatted_float
    except Exception:
        return None, None

def fetch_xml_all_versions(url):
    """Stáhne XML a vrátí seznam všech nalezených verzí FW pro danou hru"""
    if not url or not url.startswith('http'):
        return []

    req = urllib.request.Request(url, headers=HEADERS)
    raw_versions = []
    
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl_context) as response:
            xml_text = response.read().decode('utf-8', errors='ignore')
            
            if not xml_text.strip():
                return []

            try:
                root = ET.fromstring(xml_text)
                for pkg in root.findall('.//package'):
                    if 'system_ver' in pkg.attrib:
                        raw_versions.append(pkg.attrib['system_ver'])
            except Exception:
                pass

            if not raw_versions:
                matches = re.findall(r'system_ver=["\'](\d+)["\']', xml_text)
                raw_versions.extend(matches)

    except Exception:
        pass

    return raw_versions

def is_likely_dlc_title(title):
    """Detekuje, zda se jedná o DLC/doplněk podle klíčových slov v názvu"""
    dlc_keywords = [
        'costume', 'add-on', 'addon', 'expansion', 'season pass', 
        'deluxe edition pack', 'pre-order bonus', 'coin', 'points', 
        'dlc', 'bonus pack', 'item', 'bundle pack'
    ]
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in dlc_keywords)

def main():
    # Slovník pro ukládání unikátních PPSA:
    # ppsa -> { "title": str, "is_game_type": bool, "xml_urls": set() }
    games_dict = {}

    # ----------------------------------------------------
    # KROK 1: Načtení dat z GarlicSaves CSV (Hlavní zdroj)
    # ----------------------------------------------------
    print("1. Stahuji hlavní databázi z GarlicSaves (CSV)...")
    req_garlic = urllib.request.Request(GARLICSAVES_CSV_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req_garlic, timeout=20, context=ssl_context) as response:
            csv_content = response.read().decode('utf-8', errors='ignore')
            
            reader = csv.DictReader(io.StringIO(csv_content))
            for row in reader:
                title_name = row.get('title', '').strip()
                title_id = row.get('title_id', '').strip()
                package_url = row.get('package_url', '').strip()
                content_type = row.get('content_type', '').strip().lower()

                # Vytáhnutí PPSA ID z kódu
                ppsa_match = re.search(r'(PPSA\d{5})', title_id)
                if not ppsa_match:
                    continue

                ppsa = ppsa_match.group(1)
                
                # Zjištění, zda jde o plnou hru nebo DLC
                is_full_game = (content_type == 'game') and not is_likely_dlc_title(title_name)

                # Kontrola duplicit podle PPSA ID
                if ppsa not in games_dict:
                    games_dict[ppsa] = {
                        "title": title_name if title_name else ppsa,
                        "is_game_type": is_full_game,
                        "xml_urls": set()
                    }
                else:
                    # Pokud už záznam máme z DLC a teď přišel řádek s plnou hrou, nahradíme název
                    if not games_dict[ppsa]["is_game_type"] and is_full_game:
                        games_dict[ppsa]["title"] = title_name
                        games_dict[ppsa]["is_game_type"] = True

                # Odkaz na XML přidáme vždy (slouží pro zjištění verzí)
                if package_url.startswith('http'):
                    games_dict[ppsa]["xml_urls"].add(package_url)

        print(f"   Načteno a sloučeno {len(games_dict)} unikátních PS5 her/PPSA z GarlicSaves.")

    except Exception as e:
        print(f"   [!] Chyba při stahování/čtení GarlicSaves CSV: {e}")

    # ----------------------------------------------------
    # KROK 2: Doplnění dat z GitHub TSV (Záložní zdroj)
    # ----------------------------------------------------
    print("2. Doplňuji historická data z GitHub TSV...")
    req_github = urllib.request.Request(GITHUB_TSV_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req_github, timeout=15, context=ssl_context) as response:
            tsv_lines = response.read().decode('utf-8').splitlines()

            added_new = 0
            enriched_existing = 0

            for line in tsv_lines[1:]:
                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                content_id, title_name = parts[0].strip(), parts[1].strip()
                version_url = parts[2].strip() if len(parts) > 2 else ""

                ppsa_match = re.search(r'(PPSA\d{5})', content_id)
                if not ppsa_match:
                    continue

                ppsa = ppsa_match.group(1)

                if ppsa in games_dict:
                    # Pokud máme z GitHubu čistší název, než jaký byl u DLC v GarlicSaves
                    if title_name and not is_likely_dlc_title(title_name):
                        if not games_dict[ppsa]["is_game_type"] or len(title_name) > len(games_dict[ppsa]["title"]):
                            games_dict[ppsa]["title"] = title_name
                            games_dict[ppsa]["is_game_type"] = True

                    if version_url.startswith('http'):
                        games_dict[ppsa]["xml_urls"].add(version_url)
                        enriched_existing += 1
                else:
                    games_dict[ppsa] = {
                        "title": title_name,
                        "is_game_type": not is_likely_dlc_title(title_name),
                        "xml_urls": {version_url} if version_url.startswith('http') else set()
                    }
                    added_new += 1

            print(f"   Doplněno {enriched_existing} odkazů k existujícím hrám, přidáno {added_new} nových her z GitHubu.")

    except Exception as e:
        print(f"   [!] Chyba při stahování GitHub TSV: {e}")

    # ----------------------------------------------------
    # KROK 3: Stahování XML souborů a sestavení výsledku
    # ----------------------------------------------------
    print("3. Stahuji verze z XML a sestavuji výsledný JSON...")
    games_list = []
    total_games = len(games_dict)

    for idx, (ppsa, data) in enumerate(games_dict.items(), start=1):
        parsed_vers = []

        # Stáhneme verze ze všech propojených XML odkazů
        for url in data["xml_urls"]:
            raw_vers = fetch_xml_all_versions(url)
            for rv in raw_vers:
                f_str, f_num = parse_system_ver(rv)
                if f_str and f_num:
                    parsed_vers.append((f_num, f_str))

        min_fw_float = 0.0
        fw_display = "Neznámá"

        if parsed_vers:
            # Seřazení podle čísla verze od nejstarší po nejnovější
            parsed_vers.sort(key=lambda x: x[0])
            
            min_fw_float = parsed_vers[0][0]
            min_fw_str = parsed_vers[0][1]
            max_fw_str = parsed_vers[-1][1]

            if min_fw_str == max_fw_str:
                fw_display = min_fw_str
            else:
                fw_display = f"{min_fw_str} ➔ {max_fw_str}"

        games_list.append({
            "platform": "PS5",
            "ppsa": ppsa,
            "title": data["title"],
            "minFw": min_fw_float,
            "fwDisplay": fw_display
        })

        if idx % 100 == 0 or idx == total_games:
            print(f"   Zpracováno {idx}/{total_games} her...")

    # Seřazení celého seznamu abecedně podle názvu hry
    games_list.sort(key=lambda x: x['title'])

    # Uložení do souboru docs/ps5gamelist.json
    os.makedirs("docs", exist_ok=True)
    output_path = "docs/ps5gamelist.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(games_list, f, ensure_ascii=False, indent=2)

    print("--------------------------------------------------")
    print(f"HOTOVO! Celkem vygenerováno {len(games_list)} unikátních her do {output_path}.")

if __name__ == "__main__":
    main()
