"""Lightweight local HTTP server simulating a static-HTML Brazilian pharmacy catalog.

Provides paginated category pages (Medicamentos Genéricos, Vitaminas, Dermocosméticos)
with realistic Brazilian pharmacy markup: full commercial names, dosages, package counts,
list ("De") vs cash ("Por") prices, installment text, stock status variations, and
intentional cross-page duplicates for validating the cleaning and deduplication layer.
"""

from __future__ import annotations

import html
import math
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class SandboxProduct:
    """Represents a raw catalog item rendered into static HTML cards."""

    sku: str
    title: str
    active_ingredient: str
    brand: str
    category_slug: str
    category_name: str
    price_from: str | None
    price_to: str
    installment: str | None
    availability: str
    slug: str


SANDBOX_CATALOG: list[SandboxProduct] = [
    # --- Medicamentos Genéricos (Page 1 & Page 2) ---
    SandboxProduct(
        sku="MED-DIP-500-20",
        title="Dipirona Monoidratada 500mg - 20 Comprimidos - Medley - Genérico",
        active_ingredient="Dipirona Monoidratada",
        brand="Medley",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 18,90",
        price_to="Por: R$ 11,49 à vista",
        installment=None,
        availability="Em estoque",
        slug="dipirona-monoidratada-500mg-20-comprimidos-medley",
    ),
    SandboxProduct(
        sku="EMS-DIP-1G-10",
        title="Dipirona Monoidratada 1g - 10 Comprimidos - EMS - Genérico",
        active_ingredient="Dipirona Monoidratada",
        brand="EMS",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 22,50",
        price_to="Por: R$ 15,90 à vista",
        installment=None,
        availability="Avise-me quando chegar",
        slug="dipirona-monoidratada-1g-10-comprimidos-ems",
    ),
    SandboxProduct(
        sku="NEQ-DIP-500ML-20",
        title="Dipirona Monoidratada 500mg/ml Solução Oral Gotas 20ml - Neo Química - Genérico",
        active_ingredient="Dipirona Monoidratada",
        brand="Neo Química",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 14,99",
        price_to="Por: R$ 8,99",
        installment=None,
        availability="Indisponível",
        slug="dipirona-monoidratada-500mg-ml-gotas-20ml-neo-quimica",
    ),
    SandboxProduct(
        sku="EMS-LOS-50-30",
        title="Losartana Potássica 50mg c/ 30 Comprimidos Revestidos - EMS - Genérico",
        active_ingredient="Losartana Potássica",
        brand="EMS",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 29,90",
        price_to="Por: R$ 14,20 à vista",
        installment=None,
        availability="Avise-me quando chegar",
        slug="losartana-potassica-50mg-30-comprimidos-ems",
    ),
    SandboxProduct(
        sku="MED-LOS-50-60",
        title="Losartana Potássica 50mg - 60 Comprimidos Revestidos - Medley - Genérico",
        active_ingredient="Losartana Potássica",
        brand="Medley",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 54,80",
        price_to="Por: R$ 27,40 à vista",
        installment="ou 2x de R$ 13,70 sem juros",
        availability="Em estoque",
        slug="losartana-potassica-50mg-60-comprimidos-medley",
    ),
    SandboxProduct(
        sku="EUR-PAR-750-20",
        title="Paracetamol 750mg - 20 Comprimidos Revestidos - Eurofarma - Genérico",
        active_ingredient="Paracetamol",
        brand="Eurofarma",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 19,50",
        price_to="Por: R$ 12,90",
        installment=None,
        availability="Em estoque",
        slug="paracetamol-750mg-20-comprimidos-eurofarma",
    ),
    SandboxProduct(
        sku="ACH-AMO-500-21",
        title="Amoxicilina 500mg - 21 Cápsulas - Aché - Genérico",
        active_ingredient="Amoxicilina",
        brand="Aché",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 36,90",
        price_to="Por: R$ 24,50 à vista",
        installment=None,
        availability="Indisponível",
        slug="amoxicilina-500mg-21-capsulas-ache",
    ),
    SandboxProduct(
        sku="MED-AMO-875-14",
        title="Amoxicilina 875mg + Clavulanato de Potássio 125mg - 14 Comprimidos - Medley - Genérico",
        active_ingredient="Amoxicilina + Clavulanato",
        brand="Medley",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 78,90",
        price_to="Por: R$ 52,90 à vista",
        installment="ou 2x de R$ 26,45 sem juros",
        availability="Produto esgotado",
        slug="amoxicilina-875mg-clavulanato-14-comprimidos-medley",
    ),
    SandboxProduct(
        sku="EUR-OME-20-56",
        title="Omeprazol 20mg - 56 Cápsulas Duras - Eurofarma - Genérico",
        active_ingredient="Omeprazol",
        brand="Eurofarma",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 42,00",
        price_to="Por: R$ 23,10",
        installment=None,
        availability="Em estoque",
        slug="omeprazol-20mg-56-capsulas-eurofarma",
    ),
    SandboxProduct(
        sku="CIM-IBU-600-20",
        title="Ibuprofeno 600mg - 20 Comprimidos - Cimed - Genérico",
        active_ingredient="Ibuprofeno",
        brand="Cimed",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from=None,
        price_to="R$ 16,80 à vista",
        installment=None,
        availability="Disponível",
        slug="ibuprofeno-600mg-20-comprimidos-cimed",
    ),
    SandboxProduct(
        sku="SAN-MET-850-30",
        title="Cloridrato de Metformina 850mg - 30 Comprimidos - Sandoz - Genérico",
        active_ingredient="Cloridrato de Metformina",
        brand="Sandoz",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 21,90",
        price_to="Por: R$ 13,50",
        installment=None,
        availability="Em estoque",
        slug="metformina-850mg-30-comprimidos-sandoz",
    ),
    SandboxProduct(
        sku="EMS-SIM-20-30",
        title="Sinvastatina 20mg - 30 Comprimidos Revestidos - EMS - Genérico",
        active_ingredient="Sinvastatina",
        brand="EMS",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 31,40",
        price_to="Por: R$ 17,90 à vista",
        installment=None,
        availability="Temporariamente fora de estoque",
        slug="sinvastatina-20mg-30-comprimidos-ems",
    ),
    SandboxProduct(
        sku="NEQ-LOR-10-12",
        title="Loratadina 10mg - 12 Comprimidos - Neo Química - Genérico",
        active_ingredient="Loratadina",
        brand="Neo Química",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 15,90",
        price_to="Por: R$ 9,49",
        installment=None,
        availability="Em estoque",
        slug="loratadina-10mg-12-comprimidos-neo-quimica",
    ),
    SandboxProduct(
        sku="MED-AZI-500-5",
        title="Azitromicina Di-hidratada 500mg - 5 Comprimidos Revestidos - Medley - Genérico",
        active_ingredient="Azitromicina",
        brand="Medley",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 34,90",
        price_to="Por: R$ 21,90 à vista",
        installment=None,
        availability="Avise-me quando chegar",
        slug="azitromicina-500mg-5-comprimidos-medley",
    ),
    # Intentional cross-page duplicate to exercise deduplication in src/cleaner.py
    SandboxProduct(
        sku="MED-DIP-500-20",
        title="Dipirona Monoidratada 500mg - 20 Comprimidos - Medley - Genérico",
        active_ingredient="Dipirona Monoidratada",
        brand="Medley",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 18,90",
        price_to="Por: R$ 11,49 à vista",
        installment=None,
        availability="Em estoque",
        slug="dipirona-monoidratada-500mg-20-comprimidos-medley",
    ),
    SandboxProduct(
        sku="EUR-ATO-20-30",
        title="Atorvastatina Cálcica 20mg - 30 Comprimidos Revestidos - Eurofarma - Genérico",
        active_ingredient="Atorvastatina Cálcica",
        brand="Eurofarma",
        category_slug="medicamentos-genericos",
        category_name="Medicamentos Genéricos",
        price_from="De: R$ 49,90",
        price_to="Por: R$ 29,90 à vista",
        installment="ou 2x de R$ 14,95 sem juros",
        availability="Em estoque",
        slug="atorvastatina-calcica-20mg-30-comprimidos-eurofarma",
    ),
    # --- Vitaminas e Suplementos (Page 1 & Page 2) ---
    SandboxProduct(
        sku="LAV-VITD-2000-60",
        title="Vitamina D3 2000UI - 60 Cápsulas Gelatinosas - Lavitan",
        active_ingredient="Colecalciferol (Vitamina D3)",
        brand="Lavitan",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 44,90",
        price_to="Por: R$ 26,90 à vista",
        installment=None,
        availability="Avise-me quando chegar",
        slug="vitamina-d3-2000ui-60-capsulas-lavitan",
    ),
    SandboxProduct(
        sku="ADH-VITD-7000-30",
        title="Addera D3 7000UI - 30 Comprimidos Revestidos - Hypera",
        active_ingredient="Colecalciferol (Vitamina D3)",
        brand="Addera",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 89,90",
        price_to="Por: R$ 68,50 à vista",
        installment="ou 3x de R$ 22,83 sem juros",
        availability="Indisponível",
        slug="addera-d3-7000ui-30-comprimidos",
    ),
    SandboxProduct(
        sku="SUN-OMG3-1000-120",
        title="Ômega 3 Óleo de Peixe 1000mg - 120 Cápsulas - Sundown",
        active_ingredient="Ômega 3 (EPA/DHA)",
        brand="Sundown",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 119,90",
        price_to="Por: R$ 84,90 à vista",
        installment="ou 3x de R$ 28,30 sem juros",
        availability="Em estoque",
        slug="omega-3-1000mg-120-capsulas-sundown",
    ),
    SandboxProduct(
        sku="CAT-OMG3-1000-60",
        title="Ômega 3 1000mg - 60 Cápsulas Gelatinosas - Catarinense Pharma",
        active_ingredient="Ômega 3 (EPA/DHA)",
        brand="Catarinense Pharma",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 52,90",
        price_to="Por: R$ 37,90",
        installment=None,
        availability="Em estoque",
        slug="omega-3-1000mg-60-capsulas-catarinense",
    ),
    SandboxProduct(
        sku="RED-VITC-1G-30",
        title="Redoxon Vitamina C 1g - 30 Comprimidos Efervescentes - Bayer",
        active_ingredient="Ácido Ascórbico (Vitamina C)",
        brand="Bayer",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 69,90",
        price_to="Por: R$ 54,90 à vista",
        installment="ou 2x de R$ 27,45 sem juros",
        availability="Em estoque",
        slug="redoxon-vitamina-c-1g-30-comprimidos-bayer",
    ),
    SandboxProduct(
        sku="CEN-MUL-60",
        title="Centrum Essencial Multivitamínico - 60 Comprimidos - Haleon",
        active_ingredient="Polivitamínico e Minerais",
        brand="Centrum",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 109,90",
        price_to="Por: R$ 89,90 à vista",
        installment="ou 3x de R$ 29,97 sem juros",
        availability="Em estoque",
        slug="centrum-essencial-60-comprimidos",
    ),
    SandboxProduct(
        sku="LAV-MAG-350-60",
        title="Magnésio Dimalato 350mg - 60 Cápsulas - Lavitan",
        active_ingredient="Magnésio Dimalato",
        brand="Lavitan",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 49,90",
        price_to="Por: R$ 34,90 à vista",
        installment=None,
        availability="Avise-me quando chegar",
        slug="magnesio-dimalato-350mg-60-capsulas-lavitan",
    ),
    SandboxProduct(
        sku="BIO-CRE-300G",
        title="Creatina Monohidratada 300g Pote - Integralmedica",
        active_ingredient="Creatina Monohidratada",
        brand="Integralmedica",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 114,90",
        price_to="Por: R$ 79,90 à vista",
        installment="ou 3x de R$ 26,63 sem juros",
        availability="Produto esgotado",
        slug="creatina-monohidratada-300g-integralmedica",
    ),
    SandboxProduct(
        sku="CAT-B12-60",
        title="Vitamina B12 Metilcobalamina 9,94mcg - 60 Cápsulas - Catarinense Pharma",
        active_ingredient="Metilcobalamina (Vitamina B12)",
        brand="Catarinense Pharma",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from=None,
        price_to="R$ 29,90",
        installment=None,
        availability="Em estoque",
        slug="vitamina-b12-metilcobalamina-60-capsulas-catarinense",
    ),
    SandboxProduct(
        sku="LAV-COL-250G",
        title="Colágeno Hidrolisado Verisol 250g - 1 Unidade - Maxinutri",
        active_ingredient="Colágeno Hidrolisado",
        brand="Maxinutri",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 98,00",
        price_to="Por: R$ 74,90 à vista",
        installment="ou 3x de R$ 24,97 sem juros",
        availability="Em estoque",
        slug="colageno-hidrolisado-verisol-250g-maxinutri",
    ),
    # Intentional cross-page duplicate
    SandboxProduct(
        sku="SUN-OMG3-1000-120",
        title="Ômega 3 Óleo de Peixe 1000mg - 120 Cápsulas - Sundown",
        active_ingredient="Ômega 3 (EPA/DHA)",
        brand="Sundown",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 119,90",
        price_to="Por: R$ 84,90 à vista",
        installment="ou 3x de R$ 28,30 sem juros",
        availability="Em estoque",
        slug="omega-3-1000mg-120-capsulas-sundown",
    ),
    SandboxProduct(
        sku="ESS-PRO-30",
        title="Probiótico Lactobacillus 10 Bilhões UFC - 30 Cápsulas - Essential Nutrition",
        active_ingredient="Lactobacillus Acidophilus",
        brand="Essential Nutrition",
        category_slug="vitaminas",
        category_name="Vitaminas",
        price_from="De: R$ 159,00",
        price_to="Por: R$ 135,15 à vista",
        installment="ou 4x de R$ 33,79 sem juros",
        availability="Em estoque",
        slug="probiotico-lactobacillus-30-capsulas-essential",
    ),
    # --- Dermocosméticos (Page 1 & Page 2) ---
    SandboxProduct(
        sku="LRP-ANT-70-40G",
        title="Protetor Solar Facial Anthelios Airlicium FPS 70 40g - La Roche-Posay",
        active_ingredient="Filtro Solar FPS 70 + Airlicium",
        brand="La Roche-Posay",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 109,90",
        price_to="Por: R$ 87,90 à vista",
        installment="ou 3x de R$ 29,30 sem juros",
        availability="Avise-me quando chegar",
        slug="protetor-solar-anthelios-airlicium-fps70-40g-la-roche-posay",
    ),
    SandboxProduct(
        sku="ISD-FUS-60-50ML",
        title="Protetor Solar Facial Fusion Water Oil Control FPS 60 50ml - ISDIN",
        active_ingredient="Filtro Solar FPS 60 + Ácido Hialurônico",
        brand="ISDIN",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 119,90",
        price_to="Por: R$ 95,90 à vista",
        installment="ou 3x de R$ 31,97 sem juros",
        availability="Indisponível",
        slug="protetor-solar-fusion-water-fps60-50ml-isdin",
    ),
    SandboxProduct(
        sku="PRI-VC10-30ML",
        title="Sérum Facial Vitamina C 10% + Ácido Ferúlico 30ml - Principia",
        active_ingredient="Vitamina C 10% + Ácido Ferúlico",
        brand="Principia",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 69,00",
        price_to="Por: R$ 59,00 à vista",
        installment="ou 2x de R$ 29,50 sem juros",
        availability="Em estoque",
        slug="serum-vitamina-c-10-30ml-principia",
    ),
    SandboxProduct(
        sku="CER-LOC-473ML",
        title="Loção Hidratante Corporal 473ml - CeraVe",
        active_ingredient="Ceramidas + Ácido Hialurônico",
        brand="CeraVe",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 114,90",
        price_to="Por: R$ 91,90 à vista",
        installment="ou 3x de R$ 30,63 sem juros",
        availability="Em estoque",
        slug="locao-hidratante-corporal-473ml-cerave",
    ),
    SandboxProduct(
        sku="VIC-MIN89-50ML",
        title="Sérum Fortalecedor Minéral 89 50ml - Vichy",
        active_ingredient="Ácido Hialurônico + Água Vulcânica",
        brand="Vichy",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 199,90",
        price_to="Por: R$ 159,90 à vista",
        installment="ou 5x de R$ 31,98 sem juros",
        availability="Em estoque",
        slug="serum-mineral-89-50ml-vichy",
    ),
    SandboxProduct(
        sku="BIO-SEN-500ML",
        title="Água Micelar Sensibio H2O 500ml - Bioderma",
        active_ingredient="Micelas Ésteres de Ácidos Graxos",
        brand="Bioderma",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 139,90",
        price_to="Por: R$ 104,90 à vista",
        installment="ou 3x de R$ 34,97 sem juros",
        availability="Em estoque",
        slug="agua-micelar-sensibio-h2o-500ml-bioderma",
    ),
    SandboxProduct(
        sku="LRP-EFF-300G",
        title="Gel de Limpeza Facial Effaclar Concentrado 300g - La Roche-Posay",
        active_ingredient="Ácido Salicílico 2% + LHA",
        brand="La Roche-Posay",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 119,90",
        price_to="Por: R$ 94,90 à vista",
        installment="ou 3x de R$ 31,63 sem juros",
        availability="Avise-me quando chegar",
        slug="gel-limpeza-effaclar-concentrado-300g-la-roche-posay",
    ),
    SandboxProduct(
        sku="SKI-CEF-30ML",
        title="Sérum Antioxidante C E Ferulic 30ml - SkinCeuticals",
        active_ingredient="Vitamina C 15% + Vitamina E + Ácido Ferúlico",
        brand="SkinCeuticals",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 1.099,00",
        price_to="Por: R$ 989,10 à vista",
        installment="ou 10x de R$ 98,91 sem juros",
        availability="Indisponível",
        slug="serum-ce-ferulic-30ml-skinceuticals",
    ),
    SandboxProduct(
        sku="CET-CRE-453G",
        title="Creme Hidratante Pote 453g - Cetaphil",
        active_ingredient="Niacinamida + Pantenol + Glicerina",
        brand="Cetaphil",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 129,90",
        price_to="Por: R$ 99,90 à vista",
        installment="ou 3x de R$ 33,30 sem juros",
        availability="Em estoque",
        slug="creme-hidratante-453g-cetaphil",
    ),
    SandboxProduct(
        sku="EUC-ANT-30ML",
        title="Sérum Anti-Pigment Dual 30ml - Eucerin",
        active_ingredient="Thiamidol + Ácido Hialurônico",
        brand="Eucerin",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 259,90",
        price_to="Por: R$ 219,90 à vista",
        installment="ou 6x de R$ 36,65 sem juros",
        availability="Em estoque",
        slug="serum-anti-pigment-dual-30ml-eucerin",
    ),
    SandboxProduct(
        sku="MAN-EPI-60G",
        title="Protetor Solar Episol Sec OC FPS 60 60g - Mantecorp Skincare",
        active_ingredient="Filtro Solar FPS 60",
        brand="Mantecorp Skincare",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 89,90",
        price_to="Por: R$ 71,90 à vista",
        installment=None,
        availability="Produto esgotado",
        slug="protetor-solar-episol-sec-oc-fps60-60g-mantecorp",
    ),
    # Intentional cross-page duplicate
    SandboxProduct(
        sku="CER-LOC-473ML",
        title="Loção Hidratante Corporal 473ml - CeraVe",
        active_ingredient="Ceramidas + Ácido Hialurônico",
        brand="CeraVe",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 114,90",
        price_to="Por: R$ 91,90 à vista",
        installment="ou 3x de R$ 30,63 sem juros",
        availability="Em estoque",
        slug="locao-hidratante-corporal-473ml-cerave",
    ),
    SandboxProduct(
        sku="AVE-TER-300ML",
        title="Água Termal Spray 300ml - Avène",
        active_ingredient="Água Termal Avène",
        brand="Avène",
        category_slug="dermocosmeticos",
        category_name="Dermocosméticos",
        price_from="De: R$ 119,90",
        price_to="Por: R$ 89,90 à vista",
        installment="ou 3x de R$ 29,97 sem juros",
        availability="Em estoque",
        slug="agua-termal-spray-300ml-avene",
    ),
]

CATEGORIES = {
    "medicamentos-genericos": "Medicamentos Genéricos",
    "vitaminas": "Vitaminas",
    "dermocosmeticos": "Dermocosméticos",
}

ITEMS_PER_PAGE = 8


def _render_category_html(category_slug: str, page: int) -> str:
    """Render a realistic paginated static HTML category listing."""
    category_name = CATEGORIES[category_slug]
    items = [p for p in SANDBOX_CATALOG if p.category_slug == category_slug]
    total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
    start = (page - 1) * ITEMS_PER_PAGE
    page_items = items[start : start + ITEMS_PER_PAGE]

    cards_html: list[str] = []
    for item in page_items:
        price_from_html = (
            f'<span class="price-list">{html.escape(item.price_from)}</span>'
            if item.price_from
            else ""
        )
        installment_html = (
            f'<span class="price-installment">{html.escape(item.installment)}</span>'
            if item.installment
            else ""
        )
        cards_html.append(
            f"""
            <article class="product-card" data-sku="{html.escape(item.sku)}">
                <a class="product-link" href="/produto/{html.escape(item.slug)}">
                    <h2 class="product-title">{html.escape(item.title)}</h2>
                </a>
                <div class="product-meta">
                    <span class="product-active-ingredient">{html.escape(item.active_ingredient)}</span>
                    <span class="product-brand">{html.escape(item.brand)}</span>
                    <span class="product-category">{html.escape(item.category_name)}</span>
                </div>
                <div class="pricing">
                    {price_from_html}
                    <span class="price-sale">{html.escape(item.price_to)}</span>
                    {installment_html}
                </div>
                <div class="availability">
                    <span class="stock-status">{html.escape(item.availability)}</span>
                </div>
            </article>
            """
        )

    next_link = ""
    if page < total_pages:
        next_link = (
            f'<a class="pagination-next" '
            f'href="/categoria/{category_slug}?page={page + 1}">Próxima</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <title>{html.escape(category_name)} - Página {page} | Farmácia Sandbox Regional</title>
</head>
<body>
    <header>
        <h1>{html.escape(category_name)}</h1>
        <p class="page-indicator">Página {page} de {total_pages}</p>
    </header>
    <main class="product-grid">
        {"".join(cards_html)}
    </main>
    <nav class="pagination">
        {next_link}
    </nav>
</body>
</html>
"""


class _SandboxRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler serving static pharmacy category pages."""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [segment for segment in parsed.path.split("/") if segment]

        if len(parts) == 2 and parts[0] == "categoria" and parts[1] in CATEGORIES:
            query = parse_qs(parsed.query)
            try:
                page = max(1, int(query.get("page", ["1"])[0]))
            except ValueError:
                page = 1

            body = _render_category_html(parts[1], page).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path in ("/", "/health"):
            body = b"<html><body><h1>Farmacia Sandbox Catalog OK</h1></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Suppress noisy per-request stderr logs when embedded inside the pipeline.
        return


class SandboxPharmacyServer:
    """Context manager running the local pharmacy catalog HTTP server in a daemon thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Sandbox server has not been started.")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> str:
        self._server = ThreadingHTTPServer((self._host, self._port), _SandboxRequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> SandboxPharmacyServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


if __name__ == "__main__":
    with SandboxPharmacyServer(port=8765) as srv:
        print(f"Sandbox pharmacy server listening on {srv.base_url}")
        print("Categories:")
        for slug in CATEGORIES:
            print(f"  - {srv.base_url}/categoria/{slug}?page=1")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nShutting down sandbox server.")
