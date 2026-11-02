"""Airport directory, coordinates, metro area groupings, and transit hub corridors."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AirportInfo:
    code: str
    name: str
    city: str
    country: str
    region: str  # NA, EU, ASIA, ME, OC, SA
    lat: float
    lon: float
    metro_code: str
    is_major_hub: bool = False
    nearby_codes: tuple[str, ...] = ()


AIRPORTS: dict[str, AirportInfo] = {
    # North America - West
    "SFO": AirportInfo(
        "SFO", "San Francisco Intl", "San Francisco", "US", "NA", 37.6213, -122.3790, "SFO", True, ("OAK", "SJC")
    ),
    "OAK": AirportInfo(
        "OAK", "Oakland Intl", "San Francisco / Oakland", "US", "NA", 37.7213, -122.2208, "SFO", False, ("SFO", "SJC")
    ),
    "SJC": AirportInfo(
        "SJC",
        "San Jose Mineta Intl",
        "San Jose / Bay Area",
        "US",
        "NA",
        37.3639,
        -121.9289,
        "SFO",
        False,
        ("SFO", "OAK"),
    ),
    "LAX": AirportInfo(
        "LAX", "Los Angeles Intl", "Los Angeles", "US", "NA", 33.9416, -118.4085, "LAX", True, ("BUR", "SNA", "ONT")
    ),
    "BUR": AirportInfo(
        "BUR",
        "Hollywood Burbank",
        "Los Angeles / Burbank",
        "US",
        "NA",
        34.2007,
        -118.3587,
        "LAX",
        False,
        ("LAX", "SNA"),
    ),
    "SNA": AirportInfo(
        "SNA",
        "John Wayne Airport",
        "Orange County / LA",
        "US",
        "NA",
        33.6757,
        -117.8678,
        "LAX",
        False,
        ("LAX", "BUR", "ONT"),
    ),
    "ONT": AirportInfo(
        "ONT",
        "Ontario International Airport",
        "Ontario / Los Angeles",
        "US",
        "NA",
        34.0560,
        -117.6012,
        "LAX",
        False,
        ("LAX", "SNA", "BUR"),
    ),
    "SEA": AirportInfo("SEA", "Seattle-Tacoma Intl", "Seattle", "US", "NA", 47.4502, -122.3088, "SEA", True, ("YVR",)),
    "YVR": AirportInfo("YVR", "Vancouver Intl", "Vancouver", "CA", "NA", 49.1967, -123.1815, "YVR", True, ("SEA",)),
    # North America - Central / East
    "ORD": AirportInfo("ORD", "O'Hare Intl", "Chicago", "US", "NA", 41.9742, -87.9073, "CHI", True, ("MDW",)),
    "MDW": AirportInfo("MDW", "Midway Intl", "Chicago", "US", "NA", 41.7868, -87.7522, "CHI", False, ("ORD",)),
    "DFW": AirportInfo("DFW", "Dallas/Fort Worth Intl", "Dallas", "US", "NA", 32.8998, -97.0403, "DFW", True, ("DAL",)),
    "JFK": AirportInfo(
        "JFK", "John F. Kennedy Intl", "New York", "US", "NA", 40.6413, -73.7781, "NYC", True, ("EWR", "LGA")
    ),
    "EWR": AirportInfo(
        "EWR", "Newark Liberty Intl", "New York / Newark", "US", "NA", 40.6895, -74.1745, "NYC", True, ("JFK", "LGA")
    ),
    "LGA": AirportInfo("LGA", "LaGuardia", "New York", "US", "NA", 40.7769, -73.8740, "NYC", False, ("JFK", "EWR")),
    "BOS": AirportInfo("BOS", "Logan Intl", "Boston", "US", "NA", 42.3656, -71.0096, "BOS", True, ()),
    "IAD": AirportInfo(
        "IAD", "Washington Dulles Intl", "Washington D.C.", "US", "NA", 38.9531, -77.4565, "WAS", True, ("DCA", "BWI")
    ),
    "DCA": AirportInfo(
        "DCA", "Reagan National", "Washington D.C.", "US", "NA", 38.8512, -77.0402, "WAS", False, ("IAD", "BWI")
    ),
    "BWI": AirportInfo(
        "BWI",
        "Baltimore/Washington",
        "Washington / Baltimore",
        "US",
        "NA",
        39.1774,
        -76.6684,
        "WAS",
        False,
        ("IAD", "DCA"),
    ),
    "MIA": AirportInfo("MIA", "Miami Intl", "Miami", "US", "NA", 25.7959, -80.2870, "MIA", True, ("FLL",)),
    "FLL": AirportInfo(
        "FLL", "Fort Lauderdale Intl", "Miami / Fort Lauderdale", "US", "NA", 26.0742, -80.1506, "MIA", False, ("MIA",)
    ),
    "YYZ": AirportInfo("YYZ", "Toronto Pearson Intl", "Toronto", "CA", "NA", 43.6777, -79.6248, "YTO", True, ()),
    # Europe
    "LHR": AirportInfo(
        "LHR",
        "London Heathrow Airport",
        "London",
        "GB",
        "EU",
        51.4700,
        -0.4543,
        "LON",
        True,
        ("LGW", "STN", "LTN", "LCY", "SEN"),
    ),
    "LGW": AirportInfo(
        "LGW",
        "London Gatwick Airport",
        "London",
        "GB",
        "EU",
        51.1537,
        -0.1821,
        "LON",
        False,
        ("LHR", "STN", "LTN", "LCY", "SEN"),
    ),
    "STN": AirportInfo(
        "STN",
        "London Stansted Airport",
        "London",
        "GB",
        "EU",
        51.8860,
        0.2389,
        "LON",
        False,
        ("LHR", "LGW", "LTN", "LCY", "SEN"),
    ),
    "LTN": AirportInfo(
        "LTN",
        "London Luton Airport",
        "London",
        "GB",
        "EU",
        51.8747,
        -0.3683,
        "LON",
        False,
        ("LHR", "LGW", "STN", "LCY", "SEN"),
    ),
    "LCY": AirportInfo(
        "LCY",
        "London City Airport",
        "London",
        "GB",
        "EU",
        51.5048,
        0.0495,
        "LON",
        False,
        ("LHR", "LGW", "STN", "LTN", "SEN"),
    ),
    "SEN": AirportInfo(
        "SEN",
        "London Southend Airport",
        "London",
        "GB",
        "EU",
        51.5714,
        0.6956,
        "LON",
        False,
        ("LHR", "LGW", "STN", "LTN", "LCY"),
    ),
    "MAN": AirportInfo(
        "MAN", "Manchester Airport", "Manchester", "GB", "EU", 53.3537, -2.2750, "MAN", False, ("EDI", "LHR")
    ),
    "EDI": AirportInfo("EDI", "Edinburgh Airport", "Edinburgh", "GB", "EU", 55.9508, -3.3615, "EDI", False, ("MAN",)),
    "CDG": AirportInfo(
        "CDG", "Charles de Gaulle Airport", "Paris", "FR", "EU", 49.0097, 2.5479, "PAR", True, ("ORY", "BVA")
    ),
    "ORY": AirportInfo("ORY", "Paris Orly Airport", "Paris", "FR", "EU", 48.7262, 2.3652, "PAR", False, ("CDG", "BVA")),
    "BVA": AirportInfo(
        "BVA", "Paris Beauvais Airport", "Paris", "FR", "EU", 49.4544, 2.1128, "PAR", False, ("CDG", "ORY")
    ),
    "NCE": AirportInfo("NCE", "Nice Cote d'Azur Airport", "Nice", "FR", "EU", 43.6584, 7.2159, "NCE", False, ("MXP",)),
    "AMS": AirportInfo(
        "AMS", "Amsterdam Airport Schiphol", "Amsterdam", "NL", "EU", 52.3105, 4.7683, "AMS", True, ("EIN", "RTM")
    ),
    "EIN": AirportInfo(
        "EIN", "Eindhoven Airport", "Eindhoven / Amsterdam", "NL", "EU", 51.4501, 5.3745, "AMS", False, ("AMS", "RTM")
    ),
    "RTM": AirportInfo(
        "RTM",
        "Rotterdam The Hague Airport",
        "Rotterdam / Amsterdam",
        "NL",
        "EU",
        51.9569,
        4.4372,
        "AMS",
        False,
        ("AMS", "EIN"),
    ),
    "BRU": AirportInfo("BRU", "Brussels Airport", "Brussels", "BE", "EU", 50.9010, 4.4856, "BRU", False, ("CRL",)),
    "CRL": AirportInfo(
        "CRL", "Brussels South Charleroi Airport", "Brussels", "BE", "EU", 50.4592, 4.4538, "BRU", False, ("BRU",)
    ),
    "FRA": AirportInfo("FRA", "Frankfurt Airport", "Frankfurt", "DE", "EU", 50.0379, 8.5622, "FRA", True, ("HHN",)),
    "HHN": AirportInfo(
        "HHN", "Frankfurt-Hahn Airport", "Frankfurt", "DE", "EU", 49.9487, 7.2639, "FRA", False, ("FRA",)
    ),
    "MUC": AirportInfo("MUC", "Munich International Airport", "Munich", "DE", "EU", 48.3537, 11.7750, "MUC", True, ()),
    "BER": AirportInfo("BER", "Berlin Brandenburg Airport", "Berlin", "DE", "EU", 52.3667, 13.5033, "BER", False, ()),
    "ZRH": AirportInfo("ZRH", "Zurich Airport", "Zurich", "CH", "EU", 47.4582, 8.5555, "ZRH", True, ("BSL", "GVA")),
    "BSL": AirportInfo(
        "BSL",
        "EuroAirport Basel Mulhouse Freiburg",
        "Basel / Zurich",
        "CH",
        "EU",
        47.5900,
        7.5299,
        "ZRH",
        False,
        ("ZRH", "GVA"),
    ),
    "GVA": AirportInfo("GVA", "Geneva Airport", "Geneva", "CH", "EU", 46.2381, 6.1089, "GVA", False, ("ZRH", "BSL")),
    "VIE": AirportInfo(
        "VIE", "Vienna International Airport", "Vienna", "AT", "EU", 48.1103, 16.5697, "VIE", True, ("BTS",)
    ),
    "BTS": AirportInfo(
        "BTS", "Bratislava Airport", "Bratislava / Vienna", "SK", "EU", 48.1702, 17.2127, "VIE", False, ("VIE",)
    ),
    "PRG": AirportInfo("PRG", "Vaclav Havel Airport Prague", "Prague", "CZ", "EU", 50.1008, 14.2600, "PRG", False, ()),
    "BUD": AirportInfo("BUD", "Budapest Ferenc Liszt Intl", "Budapest", "HU", "EU", 47.4369, 19.2556, "BUD", False, ()),
    "FCO": AirportInfo(
        "FCO",
        "Leonardo da Vinci–Fiumicino Airport",
        "Rome",
        "IT",
        "EU",
        41.8003,
        12.2389,
        "ROM",
        True,
        ("CIA", "NAP", "FLR"),
    ),
    "CIA": AirportInfo(
        "CIA", "Rome Ciampino Airport", "Rome", "IT", "EU", 41.7994, 12.5949, "ROM", False, ("FCO", "NAP")
    ),
    "NAP": AirportInfo(
        "NAP", "Naples International Airport", "Naples", "IT", "EU", 40.8860, 14.2908, "NAP", False, ("FCO", "CIA")
    ),
    "FLR": AirportInfo(
        "FLR",
        "Florence Airport, Peretola",
        "Florence",
        "IT",
        "EU",
        43.8100,
        11.2051,
        "FLR",
        False,
        ("FCO", "VCE", "MXP"),
    ),
    "VCE": AirportInfo(
        "VCE", "Venice Marco Polo Airport", "Venice", "IT", "EU", 45.5053, 12.3519, "VCE", False, ("MXP", "FLR")
    ),
    "MXP": AirportInfo(
        "MXP", "Milan Malpensa Airport", "Milan", "IT", "EU", 45.6301, 8.7255, "MIL", True, ("LIN", "BGY")
    ),
    "LIN": AirportInfo(
        "LIN", "Milan Linate Airport", "Milan", "IT", "EU", 45.4451, 9.2767, "MIL", False, ("MXP", "BGY")
    ),
    "BGY": AirportInfo(
        "BGY", "Milan Bergamo Airport", "Milan", "IT", "EU", 45.6690, 9.7042, "MIL", False, ("MXP", "LIN")
    ),
    "MAD": AirportInfo("MAD", "Adolfo Suarez Madrid–Barajas", "Madrid", "ES", "EU", 40.4983, -3.5676, "MAD", True, ()),
    "BCN": AirportInfo(
        "BCN", "Josep Tarradellas Barcelona–El Prat", "Barcelona", "ES", "EU", 41.2974, 2.0833, "BCN", True, ("GRO",)
    ),
    "GRO": AirportInfo(
        "GRO", "Girona–Costa Brava Airport", "Girona / Barcelona", "ES", "EU", 41.9010, 2.7606, "BCN", False, ("BCN",)
    ),
    "LIS": AirportInfo(
        "LIS", "Humberto Delgado Airport", "Lisbon", "PT", "EU", 38.7756, -9.1354, "LIS", True, ("OPO",)
    ),
    "OPO": AirportInfo(
        "OPO", "Francisco Sa Carneiro Airport", "Porto", "PT", "EU", 41.2481, -8.6814, "OPO", False, ("LIS",)
    ),
    "ATH": AirportInfo(
        "ATH",
        "Athens International Airport (Eleftherios Venizelos)",
        "Athens",
        "GR",
        "EU",
        37.9364,
        23.9445,
        "ATH",
        True,
        ("JMK", "JTR", "SKG", "HER"),
    ),
    "SKG": AirportInfo(
        "SKG", "Thessaloniki Airport Makedonia", "Thessaloniki", "GR", "EU", 40.5197, 22.9709, "SKG", False, ("ATH",)
    ),
    "JTR": AirportInfo(
        "JTR",
        "Santorini International Airport",
        "Santorini",
        "GR",
        "EU",
        36.3992,
        25.4793,
        "JTR",
        False,
        ("ATH", "JMK", "HER"),
    ),
    "JMK": AirportInfo("JMK", "Mykonos Airport", "Mykonos", "GR", "EU", 37.4351, 25.3481, "JMK", False, ("ATH", "JTR")),
    "HER": AirportInfo(
        "HER",
        "Heraklion International Airport",
        "Heraklion / Crete",
        "GR",
        "EU",
        35.3397,
        25.1803,
        "HER",
        False,
        ("ATH", "JTR"),
    ),
    "CPH": AirportInfo("CPH", "Copenhagen Airport", "Copenhagen", "DK", "EU", 55.6180, 12.6508, "CPH", True, ("MMX",)),
    "MMX": AirportInfo(
        "MMX", "Malmo Airport", "Malmo / Copenhagen", "SE", "EU", 55.5363, 13.3762, "CPH", False, ("CPH",)
    ),
    "ARN": AirportInfo(
        "ARN", "Stockholm Arlanda", "Stockholm", "SE", "EU", 59.6498, 17.9238, "STO", False, ("BMA", "NYO")
    ),
    "BMA": AirportInfo("BMA", "Stockholm Bromma", "Stockholm", "SE", "EU", 59.3544, 17.9417, "STO", False, ("ARN",)),
    "HEL": AirportInfo("HEL", "Helsinki-Vantaa", "Helsinki", "FI", "EU", 60.3172, 24.9633, "HEL", True, ()),
    "DUB": AirportInfo("DUB", "Dublin Airport", "Dublin", "IE", "EU", 53.4264, -6.2499, "DUB", True, ()),
    "IST": AirportInfo("IST", "Istanbul Airport", "Istanbul", "TR", "ME", 41.2753, 28.7519, "IST", True, ("SAW",)),
    "SAW": AirportInfo("SAW", "Sabiha Gokcen", "Istanbul", "TR", "ME", 40.8986, 29.3092, "IST", False, ("IST",)),
    # Middle East
    "DXB": AirportInfo("DXB", "Dubai Intl", "Dubai", "AE", "ME", 25.2532, 55.3657, "DXB", True, ("AUH", "SHJ")),
    "SHJ": AirportInfo(
        "SHJ", "Sharjah Intl", "Sharjah / Dubai", "AE", "ME", 25.3286, 55.5172, "DXB", False, ("DXB", "AUH")
    ),
    "AUH": AirportInfo("AUH", "Zayed Intl", "Abu Dhabi", "AE", "ME", 24.4330, 54.6511, "DXB", True, ("DXB", "SHJ")),
    "DOH": AirportInfo("DOH", "Hamad Intl", "Doha", "QA", "ME", 25.2731, 51.6081, "DOH", True, ()),
    # Asia-Pacific
    "HND": AirportInfo("HND", "Tokyo Haneda", "Tokyo", "JP", "ASIA", 35.5494, 139.7798, "TYO", True, ("NRT",)),
    "NRT": AirportInfo("NRT", "Tokyo Narita", "Tokyo", "JP", "ASIA", 35.7720, 140.3929, "TYO", True, ("HND",)),
    "KIX": AirportInfo(
        "KIX", "Kansai Intl", "Osaka / Kyoto", "JP", "ASIA", 34.4320, 135.2304, "OSA", True, ("ITM", "UKB")
    ),
    "ITM": AirportInfo(
        "ITM", "Osaka Itami", "Osaka / Kyoto", "JP", "ASIA", 34.7855, 135.4382, "OSA", False, ("KIX", "UKB")
    ),
    "UKB": AirportInfo(
        "UKB", "Kobe Airport", "Kobe / Osaka", "JP", "ASIA", 34.6328, 135.2239, "OSA", False, ("KIX", "ITM")
    ),
    "ICN": AirportInfo("ICN", "Incheon Intl", "Seoul", "KR", "ASIA", 37.4602, 126.4407, "SEL", True, ("GMP",)),
    "GMP": AirportInfo("GMP", "Gimpo Intl", "Seoul", "KR", "ASIA", 37.5583, 126.7906, "SEL", False, ("ICN",)),
    "TPE": AirportInfo("TPE", "Taoyuan Intl", "Taipei", "TW", "ASIA", 25.0797, 121.2342, "TPE", True, ("TSA",)),
    "TSA": AirportInfo("TSA", "Taipei Songshan", "Taipei", "TW", "ASIA", 25.0697, 121.5525, "TPE", False, ("TPE",)),
    "HKG": AirportInfo(
        "HKG", "Hong Kong Intl", "Hong Kong", "HK", "ASIA", 22.3080, 113.9185, "HKG", True, ("MFM", "SZX")
    ),
    "MFM": AirportInfo(
        "MFM", "Macau Intl", "Macau / Hong Kong", "MO", "ASIA", 22.1496, 113.5915, "HKG", False, ("HKG",)
    ),
    "SIN": AirportInfo("SIN", "Changi Airport", "Singapore", "SG", "ASIA", 1.3644, 103.9915, "SIN", True, ()),
    "KUL": AirportInfo(
        "KUL", "Kuala Lumpur Intl", "Kuala Lumpur", "MY", "ASIA", 2.7456, 101.7072, "KUL", True, ("SZB",)
    ),
    "SZB": AirportInfo(
        "SZB", "Sultan Abdul Aziz Shah", "Kuala Lumpur", "MY", "ASIA", 3.1306, 101.5493, "KUL", False, ("KUL",)
    ),
    "BKK": AirportInfo("BKK", "Suvarnabhumi", "Bangkok", "TH", "ASIA", 13.6900, 100.7501, "BKK", True, ("DMK",)),
    "DMK": AirportInfo("DMK", "Don Mueang Intl", "Bangkok", "TH", "ASIA", 13.9126, 100.6068, "BKK", False, ("BKK",)),
    "MNL": AirportInfo("MNL", "Ninoy Aquino Intl", "Manila", "PH", "ASIA", 14.5086, 121.0194, "MNL", False, ("CRK",)),
    "CRK": AirportInfo("CRK", "Clark Intl", "Clark / Manila", "PH", "ASIA", 15.1860, 120.5600, "MNL", False, ("MNL",)),
    "DEL": AirportInfo("DEL", "Indira Gandhi Intl", "New Delhi", "IN", "ASIA", 28.5562, 77.1000, "DEL", True, ()),
    "BOM": AirportInfo("BOM", "Chhatrapati Shivaji", "Mumbai", "IN", "ASIA", 19.0896, 72.8656, "BOM", True, ()),
    "SYD": AirportInfo("SYD", "Sydney Kingsford Smith", "Sydney", "AU", "OC", -33.9399, 151.1753, "SYD", True, ()),
    "MEL": AirportInfo("MEL", "Melbourne Airport", "Melbourne", "AU", "OC", -37.6690, 144.8410, "MEL", True, ("AVV",)),
    "AVV": AirportInfo("AVV", "Avalon Airport", "Melbourne", "AU", "OC", -38.0394, 144.4694, "MEL", False, ("MEL",)),
    "AKL": AirportInfo("AKL", "Auckland Airport", "Auckland", "NZ", "OC", -37.0082, 174.7850, "AKL", True, ()),
}


COUNTRY_NAMES: dict[str, str] = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "FR": "France",
    "NL": "Netherlands",
    "BE": "Belgium",
    "DE": "Germany",
    "CH": "Switzerland",
    "AT": "Austria",
    "SK": "Slovakia",
    "CZ": "Czechia",
    "HU": "Hungary",
    "IT": "Italy",
    "ES": "Spain",
    "PT": "Portugal",
    "GR": "Greece",
    "DK": "Denmark",
    "SE": "Sweden",
    "FI": "Finland",
    "IE": "Ireland",
    "TR": "Turkey",
    "AE": "United Arab Emirates",
    "QA": "Qatar",
    "JP": "Japan",
    "KR": "South Korea",
    "TW": "Taiwan",
    "HK": "Hong Kong",
    "MO": "Macau",
    "SG": "Singapore",
    "MY": "Malaysia",
    "TH": "Thailand",
    "PH": "Philippines",
    "IN": "India",
    "AU": "Australia",
    "NZ": "New Zealand",
}

CITY_DISTANCE_MI: dict[str, int] = {
    "SFO": 13,
    "OAK": 12,
    "SJC": 34,
    "LAX": 11,
    "BUR": 12,
    "SNA": 35,
    "ONT": 38,
    "JFK": 15,
    "EWR": 11,
    "LGA": 8,
    "LHR": 14,
    "STN": 30,
    "LGW": 25,
    "LTN": 27,
    "LCY": 7,
    "SEN": 35,
    "CDG": 16,
    "ORY": 9,
    "BVA": 43,
    "FCO": 16,
    "CIA": 9,
    "MXP": 25,
    "LIN": 5,
    "BGY": 28,
    "AMS": 9,
    "RTM": 35,
    "EIN": 66,
    "ATH": 12,
    "HND": 9,
    "NRT": 37,
    "KIX": 24,
    "ITM": 9,
    "ICN": 30,
    "GMP": 10,
    "TPE": 19,
    "TSA": 3,
    "BKK": 16,
    "DMK": 13,
}

METRO_GROUPS: dict[str, dict[str, object]] = {
    "San Francisco": {"codes": ["SFO", "OAK", "SJC"], "primary": "SFO", "subtitle": "Bay Area, United States"},
    "Los Angeles": {
        "codes": ["LAX", "BUR", "SNA", "ONT"],
        "primary": "LAX",
        "subtitle": "Southern California, United States",
    },
    "New York": {"codes": ["JFK", "EWR", "LGA"], "primary": "JFK", "subtitle": "New York Metro, United States"},
    "Washington D.C.": {"codes": ["IAD", "DCA", "BWI"], "primary": "IAD", "subtitle": "Capital Region, United States"},
    "Chicago": {"codes": ["ORD", "MDW"], "primary": "ORD", "subtitle": "Illinois, United States"},
    "Miami": {"codes": ["MIA", "FLL"], "primary": "MIA", "subtitle": "South Florida, United States"},
    "London": {"codes": ["LHR", "STN", "LGW", "LTN", "LCY", "SEN"], "primary": "LHR", "subtitle": "Capital of England"},
    "Paris": {"codes": ["CDG", "ORY", "BVA"], "primary": "CDG", "subtitle": "Capital of France"},
    "Rome": {"codes": ["FCO", "CIA"], "primary": "FCO", "subtitle": "Capital of Italy"},
    "Milan": {"codes": ["MXP", "LIN", "BGY"], "primary": "MXP", "subtitle": "Lombardy, Italy"},
    "Amsterdam": {"codes": ["AMS", "RTM", "EIN"], "primary": "AMS", "subtitle": "Capital of the Netherlands"},
    "Brussels": {"codes": ["BRU", "CRL"], "primary": "BRU", "subtitle": "Capital of Belgium"},
    "Frankfurt": {"codes": ["FRA", "HHN"], "primary": "FRA", "subtitle": "Hesse, Germany"},
    "Athens": {"codes": ["ATH"], "primary": "ATH", "subtitle": "Capital of Greece"},
    "Istanbul": {"codes": ["IST", "SAW"], "primary": "IST", "subtitle": "Turkey"},
    "Dubai": {"codes": ["DXB", "AUH", "SHJ"], "primary": "DXB", "subtitle": "United Arab Emirates"},
    "Tokyo": {"codes": ["HND", "NRT"], "primary": "HND", "subtitle": "Capital of Japan"},
    "Osaka / Kyoto": {"codes": ["KIX", "ITM", "UKB"], "primary": "KIX", "subtitle": "Kansai Region, Japan"},
    "Seoul": {"codes": ["ICN", "GMP"], "primary": "ICN", "subtitle": "Capital of South Korea"},
    "Taipei": {"codes": ["TPE", "TSA"], "primary": "TPE", "subtitle": "Capital of Taiwan"},
    "Hong Kong": {"codes": ["HKG", "MFM"], "primary": "HKG", "subtitle": "Pearl River Delta"},
    "Bangkok": {"codes": ["BKK", "DMK"], "primary": "BKK", "subtitle": "Capital of Thailand"},
    "Singapore": {"codes": ["SIN"], "primary": "SIN", "subtitle": "Republic of Singapore"},
}


def get_airport(code: str) -> AirportInfo:
    """Return airport metadata, or synthesize a reasonable fallback for unknown codes."""
    upper = code.strip().upper()
    if upper in AIRPORTS:
        return AIRPORTS[upper]
    # Deterministic fallback coordinates based on code characters
    seed = sum(ord(ch) * (idx + 1) for idx, ch in enumerate(upper))
    lat = ((seed % 90) - 30) * 1.0
    lon = (((seed * 7) % 280) - 140) * 1.0
    return AirportInfo(
        code=upper,
        name=f"{upper} Airport",
        city=upper,
        country="INTL",
        region="EU" if lon > -20 and lon < 40 else ("ASIA" if lon >= 40 else "NA"),
        lat=lat,
        lon=lon,
        metro_code=upper,
        is_major_hub=False,
        nearby_codes=(),
    )


def haversine_km(code_a: str, code_b: str) -> float:
    """Compute great-circle distance in kilometers between two airport codes."""
    if code_a.upper() == code_b.upper():
        return 0.0
    a = get_airport(code_a)
    b = get_airport(code_b)
    r = 6371.0
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(hav)))


def estimate_nonstop_hours(code_a: str, code_b: str) -> float:
    """Estimate realistic block time in hours between two airports."""
    dist_km = haversine_km(code_a, code_b)
    if dist_km <= 0:
        return 0.0
    # Cruise ~830 km/h + 0.65h taxi/climb/approach
    return round((dist_km / 830.0) + 0.65, 2)


def same_metro_area(code_a: str, code_b: str) -> bool:
    """Return True if two airports belong to the same metropolitan area."""
    if code_a.upper() == code_b.upper():
        return True
    return get_airport(code_a).metro_code == get_airport(code_b).metro_code


def suggest_airports(query: str) -> list[dict[str, object]]:
    """Search cities/airports and return matching airports plus nearby alternatives."""
    q = query.strip().lower()
    results: list[dict[str, object]] = []
    seen: set[str] = set()

    for info in AIRPORTS.values():
        if (
            not q
            or q in info.code.lower()
            or q in info.city.lower()
            or q in info.name.lower()
            or q in info.metro_code.lower()
        ):
            if info.code in seen:
                continue
            seen.add(info.code)
            nearby_details = [
                {
                    "code": nb,
                    "name": AIRPORTS[nb].name,
                    "city": AIRPORTS[nb].city,
                    "same_metro": AIRPORTS[nb].metro_code == info.metro_code,
                }
                for nb in info.nearby_codes
                if nb in AIRPORTS
            ]
            results.append(
                {
                    "code": info.code,
                    "name": info.name,
                    "city": info.city,
                    "country": info.country,
                    "region": info.region,
                    "metro_code": info.metro_code,
                    "is_major_hub": info.is_major_hub,
                    "nearby": nearby_details,
                }
            )
    return results[:20]


def candidate_intermediate_hubs(origin: str, destination: str, max_hubs: int = 3) -> list[str]:
    """Find geographically sensible major transit hubs between origin and destination."""
    orig_info = get_airport(origin)
    dest_info = get_airport(destination)
    direct_km = haversine_km(origin, destination)

    # Only split legs that are medium/long haul (>= 2,200 km)
    if direct_km < 2200:
        return []

    scored_hubs: list[tuple[float, str]] = []
    for code, hub in AIRPORTS.items():
        if not hub.is_major_hub:
            continue
        if hub.metro_code in (orig_info.metro_code, dest_info.metro_code):
            continue
        d1 = haversine_km(origin, code)
        d2 = haversine_km(code, destination)
        # Each sub-leg should be meaningful (> 500 km) and total detour <= 38%
        if d1 < 500 or d2 < 500:
            continue
        detour_ratio = (d1 + d2) / max(direct_km, 1.0)
        if detour_ratio <= 1.38:
            scored_hubs.append((detour_ratio, code))

    scored_hubs.sort(key=lambda item: item[0])
    return [code for _, code in scored_hubs[:max_hubs]]
