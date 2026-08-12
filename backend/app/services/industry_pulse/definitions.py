"""Static Industry / Sector Pulse taxonomy, graph, and ETF seeds.

The rows are intentionally plain dictionaries: migrations and calculations can
consume them without coupling this seed module to ORM models.
"""
from __future__ import annotations

import math
import re
from typing import Any

from app.services.industry_pulse.labels import chinese_name

THEME_INCLUSION_THRESHOLD = 0.30
REGISTRY_ROLES = frozenset({"primary", "secondary", "reference", "benchmark"})
PULSE_ROLES = frozenset({"primary", "secondary"})


def _slug(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _base_nodes() -> tuple[tuple[dict, ...], tuple[dict, ...], tuple[dict, ...]]:
    sectors: list[dict] = []
    groups: list[dict] = []
    leaves: list[dict] = []
    for sector in _BASE_SEED:
        sector_id = f"base.{_slug(sector['name'])}"
        sector_row = {
            "id": sector_id,
            "code": sector["code"],
            "name": sector["name"],
            "name_zh": chinese_name(sector["name"]),
            "level": 1,
            "kind": "sector",
            "parent_id": None,
        }
        sectors.append(sector_row)
        for group in sector["groups"]:
            group_id = f"{sector_id}.{_slug(group['name'])}"
            group_row = {
                "id": group_id,
                "code": group["code"],
                "name": group["name"],
                "name_zh": chinese_name(group["name"]),
                "level": 2,
                "kind": "industry_group",
                "parent_id": sector_id,
            }
            groups.append(group_row)
            for leaf in group["leaves"]:
                leaf_row = {
                    "id": f"{group_id}.{_slug(leaf['name'])}",
                    "code": leaf["code"],
                    "name": leaf["name"],
                    "name_zh": chinese_name(leaf["name"]),
                    "level": 3,
                    "kind": "industry",
                    "parent_id": group_id,
                }
                leaves.append(leaf_row)
    return tuple(sectors), tuple(groups), tuple(leaves)


def _ai_nodes() -> tuple[tuple[dict, ...], tuple[dict, ...], tuple[dict, ...]]:
    categories: list[dict] = []
    groups: list[dict] = []
    nodes: list[dict] = []
    for category in _AI_SEED:
        category_slug = _slug(category["name"].removeprefix("AI "))
        category_id = f"ai.{category_slug}"
        category_row = {
            "id": category_id,
            "name": category["name"],
            "name_zh": chinese_name(category["name"]),
            "level": 1,
            "kind": "category",
            "parent_id": None,
        }
        categories.append(category_row)
        for group in category["groups"]:
            group_slug = _slug(group["name"])
            group_id = f"{category_id}.{group_slug}"
            group_row = {
                "id": group_id,
                "name": group["name"],
                "name_zh": chinese_name(group["name"]),
                "level": 2,
                "kind": "group",
                "parent_id": category_id,
            }
            groups.append(group_row)
            for node in group["nodes"]:
                node_id = f"{group_id}.{_slug(node)}"
                nodes.append({
                    "id": node_id,
                    "name": node,
                    "name_zh": chinese_name(node),
                    "level": 3,
                    "kind": "node",
                    "parent_id": group_id,
                })
    return tuple(categories), tuple(groups), tuple(nodes)


_BASE_SEED = [
  {
    "code": "01",
    "name": "TECHNOLOGY",
    "groups": [
      {
        "code": "01.01",
        "name": "Semiconductors",
        "leaves": [
          {
            "code": "01.01.01",
            "name": "AI Accelerators / GPU / High Performance Compute"
          },
          {
            "code": "01.01.02",
            "name": "Fabless Semiconductor"
          },
          {
            "code": "01.01.03",
            "name": "Integrated Device Manufacturers"
          },
          {
            "code": "01.01.04",
            "name": "Foundry / Semiconductor Manufacturing"
          },
          {
            "code": "01.01.05",
            "name": "Analog / Mixed Signal"
          },
          {
            "code": "01.01.06",
            "name": "Power Semiconductor"
          },
          {
            "code": "01.01.07",
            "name": "Memory / DRAM / NAND / HBM"
          },
          {
            "code": "01.01.08",
            "name": "Semiconductor Equipment"
          },
          {
            "code": "01.01.09",
            "name": "Wafer / Materials / Electronic Materials"
          },
          {
            "code": "01.01.10",
            "name": "Advanced Packaging / Testing"
          },
          {
            "code": "01.01.11",
            "name": "EDA / Semiconductor IP"
          },
          {
            "code": "01.01.12",
            "name": "Other Semiconductor Components"
          }
        ]
      },
      {
        "code": "01.02",
        "name": "Technology Hardware",
        "leaves": [
          {
            "code": "01.02.01",
            "name": "Servers / AI Servers"
          },
          {
            "code": "01.02.02",
            "name": "PC / Consumer Computing"
          },
          {
            "code": "01.02.03",
            "name": "Smartphones / Mobile Devices"
          },
          {
            "code": "01.02.04",
            "name": "Storage Hardware"
          },
          {
            "code": "01.02.05",
            "name": "Networking Hardware"
          },
          {
            "code": "01.02.06",
            "name": "Optical Networking"
          },
          {
            "code": "01.02.07",
            "name": "Electronic Components"
          },
          {
            "code": "01.02.08",
            "name": "Connectors / Interconnect"
          },
          {
            "code": "01.02.09",
            "name": "Sensors"
          },
          {
            "code": "01.02.10",
            "name": "Display / Imaging Hardware"
          },
          {
            "code": "01.02.11",
            "name": "Contract Electronics Manufacturing"
          }
        ]
      },
      {
        "code": "01.03",
        "name": "Software",
        "leaves": [
          {
            "code": "01.03.01",
            "name": "Enterprise Software"
          },
          {
            "code": "01.03.02",
            "name": "SaaS"
          },
          {
            "code": "01.03.03",
            "name": "Cloud Software"
          },
          {
            "code": "01.03.04",
            "name": "Database / Data Platform"
          },
          {
            "code": "01.03.05",
            "name": "Data Analytics"
          },
          {
            "code": "01.03.06",
            "name": "Cybersecurity"
          },
          {
            "code": "01.03.07",
            "name": "DevTools / Developer Infrastructure"
          },
          {
            "code": "01.03.08",
            "name": "Observability / IT Operations"
          },
          {
            "code": "01.03.09",
            "name": "ERP / CRM / Workflow"
          },
          {
            "code": "01.03.10",
            "name": "Design / Engineering Software"
          },
          {
            "code": "01.03.11",
            "name": "Vertical Software"
          },
          {
            "code": "01.03.12",
            "name": "Consumer Software"
          },
          {
            "code": "01.03.13",
            "name": "AI Software / AI Platforms"
          }
        ]
      },
      {
        "code": "01.04",
        "name": "IT Services",
        "leaves": [
          {
            "code": "01.04.01",
            "name": "IT Consulting"
          },
          {
            "code": "01.04.02",
            "name": "Outsourcing"
          },
          {
            "code": "01.04.03",
            "name": "Managed Services"
          },
          {
            "code": "01.04.04",
            "name": "Digital Transformation"
          },
          {
            "code": "01.04.05",
            "name": "Technology Distribution"
          }
        ]
      }
    ]
  },
  {
    "code": "02",
    "name": "COMMUNICATION SERVICES",
    "groups": [
      {
        "code": "02.01",
        "name": "Internet Platforms",
        "leaves": [
          {
            "code": "02.01.01",
            "name": "Search / Advertising"
          },
          {
            "code": "02.01.02",
            "name": "Social Media"
          },
          {
            "code": "02.01.03",
            "name": "Online Platforms"
          },
          {
            "code": "02.01.04",
            "name": "Creator Economy"
          },
          {
            "code": "02.01.05",
            "name": "Digital Advertising Technology"
          }
        ]
      },
      {
        "code": "02.02",
        "name": "Media & Entertainment",
        "leaves": [
          {
            "code": "02.02.01",
            "name": "Streaming"
          },
          {
            "code": "02.02.02",
            "name": "Film / Television"
          },
          {
            "code": "02.02.03",
            "name": "Music"
          },
          {
            "code": "02.02.04",
            "name": "Gaming"
          },
          {
            "code": "02.02.05",
            "name": "Publishing"
          },
          {
            "code": "02.02.06",
            "name": "Sports / Live Entertainment"
          }
        ]
      },
      {
        "code": "02.03",
        "name": "Telecommunications",
        "leaves": [
          {
            "code": "02.03.01",
            "name": "Wireless Telecom"
          },
          {
            "code": "02.03.02",
            "name": "Fixed Telecom"
          },
          {
            "code": "02.03.03",
            "name": "Broadband"
          },
          {
            "code": "02.03.04",
            "name": "Satellite Communications"
          },
          {
            "code": "02.03.05",
            "name": "Telecom Infrastructure"
          }
        ]
      }
    ]
  },
  {
    "code": "03",
    "name": "CONSUMER DISCRETIONARY",
    "groups": [
      {
        "code": "03.01",
        "name": "Automotive",
        "leaves": [
          {
            "code": "03.01.01",
            "name": "Traditional Automakers"
          },
          {
            "code": "03.01.02",
            "name": "Electric Vehicles"
          },
          {
            "code": "03.01.03",
            "name": "Autonomous Driving"
          },
          {
            "code": "03.01.04",
            "name": "Auto Parts"
          },
          {
            "code": "03.01.05",
            "name": "Auto Retail / Services"
          }
        ]
      },
      {
        "code": "03.02",
        "name": "Retail",
        "leaves": [
          {
            "code": "03.02.01",
            "name": "E-commerce"
          },
          {
            "code": "03.02.02",
            "name": "General Retail"
          },
          {
            "code": "03.02.03",
            "name": "Specialty Retail"
          },
          {
            "code": "03.02.04",
            "name": "Apparel Retail"
          },
          {
            "code": "03.02.05",
            "name": "Home Improvement"
          }
        ]
      },
      {
        "code": "03.03",
        "name": "Consumer Products",
        "leaves": [
          {
            "code": "03.03.01",
            "name": "Apparel / Footwear"
          },
          {
            "code": "03.03.02",
            "name": "Luxury Goods"
          },
          {
            "code": "03.03.03",
            "name": "Consumer Electronics"
          },
          {
            "code": "03.03.04",
            "name": "Home Appliances"
          },
          {
            "code": "03.03.05",
            "name": "Furniture / Home Products"
          }
        ]
      },
      {
        "code": "03.04",
        "name": "Leisure",
        "leaves": [
          {
            "code": "03.04.01",
            "name": "Hotels"
          },
          {
            "code": "03.04.02",
            "name": "Restaurants"
          },
          {
            "code": "03.04.03",
            "name": "Travel / Booking"
          },
          {
            "code": "03.04.04",
            "name": "Casinos / Resorts"
          },
          {
            "code": "03.04.05",
            "name": "Recreation"
          }
        ]
      },
      {
        "code": "03.05",
        "name": "Housing",
        "leaves": [
          {
            "code": "03.05.01",
            "name": "Homebuilders"
          },
          {
            "code": "03.05.02",
            "name": "Building-related Consumer Products"
          }
        ]
      }
    ]
  },
  {
    "code": "04",
    "name": "CONSUMER STAPLES",
    "groups": [
      {
        "code": "04.01",
        "name": "Food",
        "leaves": [
          {
            "code": "04.01.01",
            "name": "Packaged Food"
          },
          {
            "code": "04.01.02",
            "name": "Agricultural Products"
          },
          {
            "code": "04.01.03",
            "name": "Meat / Protein"
          },
          {
            "code": "04.01.04",
            "name": "Ingredients"
          }
        ]
      },
      {
        "code": "04.02",
        "name": "Beverages",
        "leaves": [
          {
            "code": "04.02.01",
            "name": "Soft Drinks"
          },
          {
            "code": "04.02.02",
            "name": "Alcoholic Beverages"
          },
          {
            "code": "04.02.03",
            "name": "Coffee / Specialty Beverage"
          }
        ]
      },
      {
        "code": "04.03",
        "name": "Household & Personal",
        "leaves": [
          {
            "code": "04.03.01",
            "name": "Household Products"
          },
          {
            "code": "04.03.02",
            "name": "Personal Care"
          },
          {
            "code": "04.03.03",
            "name": "Beauty"
          }
        ]
      },
      {
        "code": "04.04",
        "name": "Staples Retail",
        "leaves": [
          {
            "code": "04.04.01",
            "name": "Grocery"
          },
          {
            "code": "04.04.02",
            "name": "Warehouse Clubs"
          },
          {
            "code": "04.04.03",
            "name": "Pharmacy Retail"
          }
        ]
      },
      {
        "code": "04.05",
        "name": "Tobacco",
        "leaves": [
          {
            "code": "04.05.01",
            "name": "Tobacco"
          },
          {
            "code": "04.05.02",
            "name": "Nicotine Products"
          }
        ]
      }
    ]
  },
  {
    "code": "05",
    "name": "HEALTHCARE",
    "groups": [
      {
        "code": "05.01",
        "name": "Pharmaceuticals",
        "leaves": [
          {
            "code": "05.01.01",
            "name": "Large Pharma"
          },
          {
            "code": "05.01.02",
            "name": "Specialty Pharma"
          },
          {
            "code": "05.01.03",
            "name": "Generic Drugs"
          }
        ]
      },
      {
        "code": "05.02",
        "name": "Biotechnology",
        "leaves": [
          {
            "code": "05.02.01",
            "name": "Large-cap Biotech"
          },
          {
            "code": "05.02.02",
            "name": "Emerging Biotech"
          },
          {
            "code": "05.02.03",
            "name": "Gene / Cell Therapy"
          },
          {
            "code": "05.02.04",
            "name": "RNA / Genetic Medicine"
          }
        ]
      },
      {
        "code": "05.03",
        "name": "Medical Technology",
        "leaves": [
          {
            "code": "05.03.01",
            "name": "Medical Devices"
          },
          {
            "code": "05.03.02",
            "name": "Surgical Robotics"
          },
          {
            "code": "05.03.03",
            "name": "Cardiovascular Devices"
          },
          {
            "code": "05.03.04",
            "name": "Diabetes Technology"
          },
          {
            "code": "05.03.05",
            "name": "Imaging Equipment"
          }
        ]
      },
      {
        "code": "05.04",
        "name": "Life Science Tools",
        "leaves": [
          {
            "code": "05.04.01",
            "name": "Diagnostics"
          },
          {
            "code": "05.04.02",
            "name": "Sequencing / Genomics"
          },
          {
            "code": "05.04.03",
            "name": "Laboratory Equipment"
          },
          {
            "code": "05.04.04",
            "name": "CRO / Research Services"
          }
        ]
      },
      {
        "code": "05.05",
        "name": "Healthcare Services",
        "leaves": [
          {
            "code": "05.05.01",
            "name": "Managed Care"
          },
          {
            "code": "05.05.02",
            "name": "Hospitals"
          },
          {
            "code": "05.05.03",
            "name": "Clinics"
          },
          {
            "code": "05.05.04",
            "name": "Healthcare IT"
          },
          {
            "code": "05.05.05",
            "name": "Digital Health"
          },
          {
            "code": "05.05.06",
            "name": "Pharmacy Benefit Management"
          }
        ]
      }
    ]
  },
  {
    "code": "06",
    "name": "FINANCIALS",
    "groups": [
      {
        "code": "06.01",
        "name": "Banks",
        "leaves": [
          {
            "code": "06.01.01",
            "name": "Money Center Banks"
          },
          {
            "code": "06.01.02",
            "name": "Regional Banks"
          },
          {
            "code": "06.01.03",
            "name": "Digital Banks"
          }
        ]
      },
      {
        "code": "06.02",
        "name": "Capital Markets",
        "leaves": [
          {
            "code": "06.02.01",
            "name": "Investment Banks"
          },
          {
            "code": "06.02.02",
            "name": "Brokers"
          },
          {
            "code": "06.02.03",
            "name": "Exchanges"
          },
          {
            "code": "06.02.04",
            "name": "Market Data / Ratings"
          },
          {
            "code": "06.02.05",
            "name": "Trading Infrastructure"
          }
        ]
      },
      {
        "code": "06.03",
        "name": "Asset Management",
        "leaves": [
          {
            "code": "06.03.01",
            "name": "Traditional Asset Managers"
          },
          {
            "code": "06.03.02",
            "name": "Alternative Asset Managers"
          },
          {
            "code": "06.03.03",
            "name": "Private Equity"
          },
          {
            "code": "06.03.04",
            "name": "Wealth Management"
          }
        ]
      },
      {
        "code": "06.04",
        "name": "Insurance",
        "leaves": [
          {
            "code": "06.04.01",
            "name": "Property & Casualty"
          },
          {
            "code": "06.04.02",
            "name": "Life Insurance"
          },
          {
            "code": "06.04.03",
            "name": "Reinsurance"
          },
          {
            "code": "06.04.04",
            "name": "Insurance Brokers"
          }
        ]
      },
      {
        "code": "06.05",
        "name": "Payments & FinTech",
        "leaves": [
          {
            "code": "06.05.01",
            "name": "Card Networks"
          },
          {
            "code": "06.05.02",
            "name": "Payment Processors"
          },
          {
            "code": "06.05.03",
            "name": "FinTech Platforms"
          },
          {
            "code": "06.05.04",
            "name": "Lending Technology"
          }
        ]
      },
      {
        "code": "06.06",
        "name": "Consumer Finance",
        "leaves": [
          {
            "code": "06.06.01",
            "name": "Credit Cards"
          },
          {
            "code": "06.06.02",
            "name": "Consumer Lending"
          },
          {
            "code": "06.06.03",
            "name": "Mortgage Finance"
          }
        ]
      }
    ]
  },
  {
    "code": "07",
    "name": "INDUSTRIALS",
    "groups": [
      {
        "code": "07.01",
        "name": "Aerospace & Defense",
        "leaves": [
          {
            "code": "07.01.01",
            "name": "Defense Prime Contractors"
          },
          {
            "code": "07.01.02",
            "name": "Aerospace"
          },
          {
            "code": "07.01.03",
            "name": "Defense Electronics"
          },
          {
            "code": "07.01.04",
            "name": "Drones / Unmanned Systems"
          },
          {
            "code": "07.01.05",
            "name": "Space Technology"
          }
        ]
      },
      {
        "code": "07.02",
        "name": "Machinery",
        "leaves": [
          {
            "code": "07.02.01",
            "name": "Heavy Machinery"
          },
          {
            "code": "07.02.02",
            "name": "Industrial Machinery"
          },
          {
            "code": "07.02.03",
            "name": "Factory Automation"
          },
          {
            "code": "07.02.04",
            "name": "Robotics"
          },
          {
            "code": "07.02.05",
            "name": "Precision Equipment"
          }
        ]
      },
      {
        "code": "07.03",
        "name": "Electrical Equipment",
        "leaves": [
          {
            "code": "07.03.01",
            "name": "Grid Equipment"
          },
          {
            "code": "07.03.02",
            "name": "Transformers"
          },
          {
            "code": "07.03.03",
            "name": "Switchgear"
          },
          {
            "code": "07.03.04",
            "name": "Power Management"
          },
          {
            "code": "07.03.05",
            "name": "Industrial Electrical Systems"
          }
        ]
      },
      {
        "code": "07.04",
        "name": "Construction & Infrastructure",
        "leaves": [
          {
            "code": "07.04.01",
            "name": "Engineering & Construction"
          },
          {
            "code": "07.04.02",
            "name": "Infrastructure Contractors"
          },
          {
            "code": "07.04.03",
            "name": "Building Products"
          },
          {
            "code": "07.04.04",
            "name": "HVAC"
          },
          {
            "code": "07.04.05",
            "name": "Data Center Cooling"
          }
        ]
      },
      {
        "code": "07.05",
        "name": "Transportation",
        "leaves": [
          {
            "code": "07.05.01",
            "name": "Airlines"
          },
          {
            "code": "07.05.02",
            "name": "Railroads"
          },
          {
            "code": "07.05.03",
            "name": "Trucking"
          },
          {
            "code": "07.05.04",
            "name": "Shipping"
          },
          {
            "code": "07.05.05",
            "name": "Logistics"
          },
          {
            "code": "07.05.06",
            "name": "Delivery"
          }
        ]
      },
      {
        "code": "07.06",
        "name": "Commercial Services",
        "leaves": [
          {
            "code": "07.06.01",
            "name": "Professional Services"
          },
          {
            "code": "07.06.02",
            "name": "Staffing"
          },
          {
            "code": "07.06.03",
            "name": "Waste Management"
          },
          {
            "code": "07.06.04",
            "name": "Environmental Services"
          },
          {
            "code": "07.06.05",
            "name": "Security Services"
          }
        ]
      }
    ]
  },
  {
    "code": "08",
    "name": "ENERGY",
    "groups": [
      {
        "code": "08.01",
        "name": "Oil & Gas",
        "leaves": [
          {
            "code": "08.01.01",
            "name": "Integrated Oil & Gas"
          },
          {
            "code": "08.01.02",
            "name": "Exploration & Production"
          },
          {
            "code": "08.01.03",
            "name": "Refining"
          },
          {
            "code": "08.01.04",
            "name": "Oilfield Services"
          },
          {
            "code": "08.01.05",
            "name": "Oilfield Equipment"
          }
        ]
      },
      {
        "code": "08.02",
        "name": "Midstream",
        "leaves": [
          {
            "code": "08.02.01",
            "name": "Pipelines"
          },
          {
            "code": "08.02.02",
            "name": "Storage"
          },
          {
            "code": "08.02.03",
            "name": "LNG Infrastructure"
          },
          {
            "code": "08.02.04",
            "name": "Natural Gas Infrastructure"
          }
        ]
      },
      {
        "code": "08.03",
        "name": "Coal",
        "leaves": [
          {
            "code": "08.03.01",
            "name": "Thermal Coal"
          },
          {
            "code": "08.03.02",
            "name": "Metallurgical Coal"
          }
        ]
      },
      {
        "code": "08.04",
        "name": "Emerging Energy",
        "leaves": [
          {
            "code": "08.04.01",
            "name": "Hydrogen"
          },
          {
            "code": "08.04.02",
            "name": "Alternative Fuels"
          }
        ]
      }
    ]
  },
  {
    "code": "09",
    "name": "MATERIALS",
    "groups": [
      {
        "code": "09.01",
        "name": "Metals & Mining",
        "leaves": [
          {
            "code": "09.01.01",
            "name": "Copper"
          },
          {
            "code": "09.01.02",
            "name": "Aluminum"
          },
          {
            "code": "09.01.03",
            "name": "Steel"
          },
          {
            "code": "09.01.04",
            "name": "Iron Ore"
          },
          {
            "code": "09.01.05",
            "name": "Gold"
          },
          {
            "code": "09.01.06",
            "name": "Silver"
          },
          {
            "code": "09.01.07",
            "name": "Lithium"
          },
          {
            "code": "09.01.08",
            "name": "Nickel"
          },
          {
            "code": "09.01.09",
            "name": "Rare Earths"
          },
          {
            "code": "09.01.10",
            "name": "Uranium Mining"
          },
          {
            "code": "09.01.11",
            "name": "Diversified Mining"
          }
        ]
      },
      {
        "code": "09.02",
        "name": "Chemicals",
        "leaves": [
          {
            "code": "09.02.01",
            "name": "Commodity Chemicals"
          },
          {
            "code": "09.02.02",
            "name": "Specialty Chemicals"
          },
          {
            "code": "09.02.03",
            "name": "Electronic Chemicals"
          },
          {
            "code": "09.02.04",
            "name": "Industrial Gases"
          },
          {
            "code": "09.02.05",
            "name": "Agricultural Chemicals"
          }
        ]
      },
      {
        "code": "09.03",
        "name": "Materials",
        "leaves": [
          {
            "code": "09.03.01",
            "name": "Construction Materials"
          },
          {
            "code": "09.03.02",
            "name": "Packaging"
          },
          {
            "code": "09.03.03",
            "name": "Paper / Forest Products"
          }
        ]
      }
    ]
  },
  {
    "code": "10",
    "name": "UTILITIES & POWER",
    "groups": [
      {
        "code": "10.01",
        "name": "Electric Utilities",
        "leaves": [
          {
            "code": "10.01.01",
            "name": "Regulated Electric Utilities"
          },
          {
            "code": "10.01.02",
            "name": "Diversified Utilities"
          }
        ]
      },
      {
        "code": "10.02",
        "name": "Independent Power",
        "leaves": [
          {
            "code": "10.02.01",
            "name": "Independent Power Producers"
          },
          {
            "code": "10.02.02",
            "name": "Merchant Power"
          }
        ]
      },
      {
        "code": "10.03",
        "name": "Nuclear Power",
        "leaves": [
          {
            "code": "10.03.01",
            "name": "Nuclear Generation"
          },
          {
            "code": "10.03.02",
            "name": "Advanced Nuclear / SMR"
          },
          {
            "code": "10.03.03",
            "name": "Nuclear Engineering / Services"
          }
        ]
      },
      {
        "code": "10.04",
        "name": "Renewable Generation",
        "leaves": [
          {
            "code": "10.04.01",
            "name": "Solar Generation"
          },
          {
            "code": "10.04.02",
            "name": "Wind Generation"
          },
          {
            "code": "10.04.03",
            "name": "Hydro"
          },
          {
            "code": "10.04.04",
            "name": "Renewable IPP"
          }
        ]
      },
      {
        "code": "10.05",
        "name": "Other Utilities",
        "leaves": [
          {
            "code": "10.05.01",
            "name": "Natural Gas Utilities"
          },
          {
            "code": "10.05.02",
            "name": "Water Utilities"
          }
        ]
      }
    ]
  },
  {
    "code": "11",
    "name": "REAL ESTATE",
    "groups": [
      {
        "code": "11.01",
        "name": "Digital Infrastructure",
        "leaves": [
          {
            "code": "11.01.01",
            "name": "Data Center REIT"
          },
          {
            "code": "11.01.02",
            "name": "Telecom Tower REIT"
          },
          {
            "code": "11.01.03",
            "name": "Fiber / Digital Infrastructure"
          }
        ]
      },
      {
        "code": "11.02",
        "name": "Commercial Real Estate",
        "leaves": [
          {
            "code": "11.02.01",
            "name": "Industrial / Logistics REIT"
          },
          {
            "code": "11.02.02",
            "name": "Office REIT"
          },
          {
            "code": "11.02.03",
            "name": "Retail REIT"
          },
          {
            "code": "11.02.04",
            "name": "Hotel REIT"
          }
        ]
      },
      {
        "code": "11.03",
        "name": "Residential",
        "leaves": [
          {
            "code": "11.03.01",
            "name": "Apartment REIT"
          },
          {
            "code": "11.03.02",
            "name": "Single-family Rental"
          },
          {
            "code": "11.03.03",
            "name": "Manufactured Housing"
          }
        ]
      },
      {
        "code": "11.04",
        "name": "Specialized Real Estate",
        "leaves": [
          {
            "code": "11.04.01",
            "name": "Healthcare REIT"
          },
          {
            "code": "11.04.02",
            "name": "Storage REIT"
          },
          {
            "code": "11.04.03",
            "name": "Gaming REIT"
          },
          {
            "code": "11.04.04",
            "name": "Other Specialized REIT"
          }
        ]
      }
    ]
  }
]
_AI_SEED = [
  {
    "name": "AI COMPUTE",
    "groups": [
      {
        "name": "Accelerators",
        "nodes": [
          "GPU / AI Accelerator",
          "Custom ASIC",
          "AI CPU",
          "Edge AI Chips"
        ]
      },
      {
        "name": "Semiconductor Production",
        "nodes": [
          "Foundry",
          "Wafer",
          "Semiconductor Equipment",
          "Advanced Packaging",
          "Testing",
          "Electronic Materials"
        ]
      },
      {
        "name": "Memory",
        "nodes": [
          "HBM",
          "DRAM",
          "NAND",
          "Storage"
        ]
      },
      {
        "name": "Semiconductor Design Infrastructure",
        "nodes": [
          "EDA",
          "Semiconductor IP"
        ]
      }
    ]
  },
  {
    "name": "AI INFRASTRUCTURE",
    "groups": [
      {
        "name": "Servers",
        "nodes": [
          "AI Servers",
          "Server Components",
          "Rack Infrastructure"
        ]
      },
      {
        "name": "Networking",
        "nodes": [
          "Ethernet",
          "AI Networking",
          "Switches",
          "High-speed Interconnect"
        ]
      },
      {
        "name": "Optical",
        "nodes": [
          "Optical Networking",
          "Optical Components",
          "Fiber"
        ]
      },
      {
        "name": "Data Centers",
        "nodes": [
          "Data Center Operators",
          "Data Center REIT",
          "Digital Infrastructure"
        ]
      },
      {
        "name": "Cooling",
        "nodes": [
          "HVAC",
          "Liquid Cooling",
          "Thermal Management"
        ]
      },
      {
        "name": "Cloud",
        "nodes": [
          "Hyperscalers",
          "IaaS",
          "PaaS"
        ]
      }
    ]
  },
  {
    "name": "AI POWER",
    "groups": [
      {
        "name": "Power Generation",
        "nodes": [
          "Nuclear",
          "Advanced Nuclear / SMR",
          "Independent Power Producers",
          "Natural Gas Power",
          "Renewable Power"
        ]
      },
      {
        "name": "Nuclear Fuel Cycle",
        "nodes": [
          "Uranium Mining",
          "Uranium Enrichment",
          "Nuclear Fuel",
          "Nuclear Equipment"
        ]
      },
      {
        "name": "Grid",
        "nodes": [
          "Grid Infrastructure",
          "Transmission",
          "Transformers",
          "Switchgear",
          "Power Management"
        ]
      },
      {
        "name": "Energy Storage",
        "nodes": [
          "Battery",
          "Grid Storage"
        ]
      }
    ]
  },
  {
    "name": "AI SOFTWARE & DATA",
    "groups": [
      {
        "name": "AI Platforms",
        "nodes": [
          "Foundation Model Ecosystem",
          "AI Development Platforms",
          "AI Infrastructure Software"
        ]
      },
      {
        "name": "Enterprise AI",
        "nodes": [
          "Enterprise Software",
          "Productivity",
          "CRM",
          "ERP",
          "Workflow"
        ]
      },
      {
        "name": "Data",
        "nodes": [
          "Database",
          "Data Warehouse",
          "Data Lake",
          "Data Analytics",
          "Observability"
        ]
      },
      {
        "name": "Cybersecurity",
        "nodes": [
          "Network Security",
          "Cloud Security",
          "Identity",
          "Endpoint Security"
        ]
      },
      {
        "name": "Developer Ecosystem",
        "nodes": [
          "DevTools",
          "CI/CD",
          "Developer Platforms"
        ]
      }
    ]
  },
  {
    "name": "AI APPLICATIONS",
    "groups": [
      {
        "name": "Robotics",
        "nodes": [
          "Industrial Robotics",
          "Humanoid Robotics",
          "Warehouse Automation"
        ]
      },
      {
        "name": "Autonomous Systems",
        "nodes": [
          "Autonomous Vehicles",
          "ADAS",
          "Drones"
        ]
      },
      {
        "name": "Healthcare AI",
        "nodes": [
          "Drug Discovery",
          "Diagnostics AI",
          "Medical Imaging",
          "Precision Medicine"
        ]
      },
      {
        "name": "Financial AI",
        "nodes": [
          "FinTech",
          "Payments",
          "Trading Infrastructure",
          "Risk / Data"
        ]
      },
      {
        "name": "Defense AI",
        "nodes": [
          "Autonomous Defense",
          "Defense Software",
          "Sensors",
          "Drones"
        ]
      },
      {
        "name": "Consumer AI",
        "nodes": [
          "AI Devices",
          "AI Applications",
          "Search / Assistants"
        ]
      }
    ]
  }
]


# The curated basket is deliberately separate from ``AI_NODE_SEED_CANDIDATES``:
# these rows are configured memberships, not discovery evidence.  Keep one
# mapping per node so a symbol can carry different role/purity/weight metadata
# in each theme node.
MANUAL_CURATED_SEED_SOURCE = "MANUAL_CURATED_SEED"
MANUAL_SEED_VERSION = "manual-curated-v1"
MANUAL_SEED_TARGET_CONSTITUENTS = 10
MANUAL_SEED_PREFERRED_RANGE = (8, 12)
MANUAL_SEED_MIN_CONSTITUENTS = 5
MANUAL_SEED_ROLE_FACTORS = {"CORE": 1.0, "SECONDARY": 0.75, "ENABLER": 0.5}
MANUAL_SEED_DEFAULT_ROLES = ("CORE", "CORE", "CORE", "SECONDARY", "SECONDARY", "SECONDARY", "SECONDARY", "SECONDARY", "ENABLER", "ENABLER")

MANUAL_CURATED_SEED_SYMBOLS: dict[str, tuple[str, ...]] = {
    "ai.compute.accelerators": ("NVDA", "AMD", "AVGO", "MRVL", "ARM", "QCOM", "INTC", "NXPI", "ALAB", "CRDO"),
    "ai.compute.semiconductor_production": ("TSM", "ASML", "AMAT", "LRCX", "KLAC", "TER", "ENTG", "MKSI", "ACLS", "CAMT"),
    "ai.compute.memory": ("MU", "SNDK", "WDC", "STX", "SIMO", "RMBS", "NTAP", "PSTG", "MRVL", "MCHP"),
    "ai.compute.semiconductor_design_infrastructure": ("SNPS", "CDNS", "ARM", "RMBS", "CEVA", "PDFS", "KEYS", "TER", "LSCC", "MCHP"),
    "ai.infrastructure.servers": ("DELL", "SMCI", "HPE", "IBM", "VRT", "NTAP", "PSTG", "CSCO", "WDC", "STX"),
    "ai.infrastructure.networking": ("ANET", "CSCO", "AVGO", "MRVL", "ALAB", "CRDO", "CIEN", "LITE", "COHR", "FN"),
    "ai.infrastructure.optical": ("COHR", "LITE", "CIEN", "AAOI", "FN", "GLW", "CALX", "ADTN", "VIAV", "IPGP"),
    "ai.infrastructure.data_centers": ("EQIX", "DLR", "IRM", "APLD", "NBIS", "CRWV", "IREN", "WULF", "GDS", "VNET"),
    "ai.infrastructure.cooling": ("VRT", "TT", "CARR", "JCI", "MOD", "AAON", "FIX", "LII", "SPXC", "NVT"),
    "ai.infrastructure.cloud": ("MSFT", "AMZN", "GOOGL", "ORCL", "IBM", "CRWV", "NBIS", "NET", "DOCN", "AKAM"),
    "ai.power.power_generation": ("CEG", "VST", "NRG", "TLN", "AES", "NEE", "SO", "EXC", "D", "PEG"),
    "ai.power.nuclear_fuel_cycle": ("CCJ", "LEU", "UEC", "UUUU", "NXE", "DNN", "URG", "EU", "BWXT", "LTBR"),
    "ai.power.grid": ("ETN", "GEV", "HUBB", "PWR", "NVT", "MYRG", "POWL", "EMR", "AME", "GNRC"),
    "ai.power.energy_storage": ("FLNC", "EOSE", "TSLA", "ALB", "AES", "ENVX", "QS", "AMPX", "SLDP", "MVST"),
    "ai.software_and_data.ai_platforms": ("MSFT", "GOOGL", "AMZN", "META", "ORCL", "IBM", "PLTR", "CRM", "NOW", "SNOW"),
    "ai.software_and_data.enterprise_ai": ("MSFT", "CRM", "NOW", "ORCL", "SAP", "IBM", "PLTR", "ADBE", "INTU", "WDAY"),
    "ai.software_and_data.data": ("SNOW", "DDOG", "MDB", "ESTC", "CFLT", "ORCL", "PLTR", "TDC", "DT", "GTLB"),
    "ai.software_and_data.cybersecurity": ("PANW", "CRWD", "FTNT", "ZS", "OKTA", "S", "CHKP", "TENB", "QLYS", "GEN"),
    "ai.software_and_data.developer_ecosystem": ("MSFT", "GTLB", "NET", "DDOG", "CFLT", "ESTC", "MDB", "DOCN", "TWLO", "AKAM"),
    "ai.applications.robotics": ("ISRG", "ROK", "TER", "SYM", "PATH", "CGNX", "ZBRA", "HON", "EMR", "NVDA"),
    "ai.applications.autonomous_systems": ("TSLA", "MBLY", "AUR", "QCOM", "NVDA", "AVAV", "KTOS", "OUST", "AEVA", "JOBY"),
    "ai.applications.healthcare_ai": ("TEM", "RXRX", "SDGR", "GH", "GEHC", "ISRG", "NTRA", "CERT", "SOPH", "BFLY"),
    "ai.applications.financial_ai": ("SPGI", "ICE", "IBKR", "HOOD", "SOFI", "XYZ", "PYPL", "UPST", "LMND", "COIN"),
    "ai.applications.defense_ai": ("PLTR", "AVAV", "KTOS", "LHX", "NOC", "RTX", "LDOS", "BAH", "RCAT", "CACI"),
    "ai.applications.consumer_ai": ("AAPL", "GOOGL", "META", "AMZN", "MSFT", "ADBE", "DUOL", "SNAP", "PINS", "SPOT"),
}

# Explicit exceptions keep broad, cross-node companies from becoming CORE in
# every theme while preserving the ordering signal in the canonical lists.
_MANUAL_ROLE_OVERRIDES: dict[str, dict[str, str]] = {
    "ai.compute.accelerators": {"ALAB": "ENABLER", "CRDO": "ENABLER"},
    "ai.compute.semiconductor_production": {"TSM": "CORE", "ASML": "CORE", "AMAT": "CORE", "LRCX": "CORE", "KLAC": "CORE", "TER": "SECONDARY"},
    "ai.compute.memory": {"MU": "CORE", "SNDK": "CORE", "WDC": "CORE", "STX": "CORE", "MRVL": "ENABLER", "MCHP": "ENABLER"},
    "ai.compute.semiconductor_design_infrastructure": {"SNPS": "CORE", "CDNS": "CORE", "ARM": "CORE", "RMBS": "CORE", "TER": "ENABLER", "MCHP": "ENABLER"},
    "ai.infrastructure.servers": {"DELL": "CORE", "SMCI": "CORE", "HPE": "CORE", "IBM": "SECONDARY", "VRT": "SECONDARY", "CSCO": "ENABLER"},
    "ai.infrastructure.networking": {"AVGO": "SECONDARY", "MRVL": "SECONDARY", "ALAB": "ENABLER", "CRDO": "ENABLER", "COHR": "ENABLER", "FN": "ENABLER"},
    "ai.infrastructure.data_centers": {"APLD": "CORE", "NBIS": "SECONDARY", "CRWV": "SECONDARY", "IREN": "SECONDARY", "WULF": "SECONDARY", "GDS": "SECONDARY", "VNET": "SECONDARY"},
    "ai.infrastructure.cooling": {"VRT": "CORE", "TT": "CORE", "CARR": "CORE", "NVT": "SECONDARY"},
    "ai.infrastructure.cloud": {"MSFT": "CORE", "AMZN": "CORE", "GOOGL": "CORE", "ORCL": "SECONDARY", "IBM": "SECONDARY", "CRWV": "SECONDARY", "NBIS": "SECONDARY", "NET": "SECONDARY"},
    "ai.power.power_generation": {"CEG": "CORE", "VST": "CORE", "NRG": "CORE", "TLN": "CORE", "AES": "SECONDARY", "NEE": "SECONDARY", "SO": "SECONDARY", "EXC": "SECONDARY", "D": "SECONDARY", "PEG": "SECONDARY"},
    "ai.power.nuclear_fuel_cycle": {"CCJ": "CORE", "LEU": "CORE", "UEC": "CORE", "UUUU": "CORE", "NXE": "CORE", "DNN": "CORE", "URG": "CORE", "EU": "CORE", "BWXT": "SECONDARY", "LTBR": "ENABLER"},
    "ai.power.grid": {"ETN": "CORE", "GEV": "CORE", "HUBB": "CORE", "PWR": "CORE", "NVT": "CORE", "MYRG": "SECONDARY", "POWL": "SECONDARY", "EMR": "SECONDARY", "AME": "ENABLER", "GNRC": "ENABLER"},
    "ai.power.energy_storage": {"FLNC": "CORE", "EOSE": "CORE", "TSLA": "SECONDARY", "ALB": "SECONDARY", "AES": "SECONDARY", "ENVX": "CORE", "QS": "CORE", "AMPX": "ENABLER", "SLDP": "ENABLER", "MVST": "ENABLER"},
    "ai.software_and_data.ai_platforms": {"MSFT": "CORE", "GOOGL": "CORE", "AMZN": "CORE", "META": "CORE", "ORCL": "SECONDARY", "IBM": "SECONDARY", "PLTR": "SECONDARY", "CRM": "SECONDARY", "NOW": "SECONDARY", "SNOW": "SECONDARY"},
    "ai.software_and_data.enterprise_ai": {"MSFT": "CORE", "CRM": "CORE", "NOW": "CORE", "ORCL": "CORE", "SAP": "CORE", "IBM": "SECONDARY", "PLTR": "SECONDARY", "ADBE": "SECONDARY", "INTU": "SECONDARY", "WDAY": "SECONDARY"},
    "ai.software_and_data.data": {"SNOW": "CORE", "DDOG": "CORE", "MDB": "CORE", "ESTC": "CORE", "CFLT": "CORE", "ORCL": "SECONDARY", "PLTR": "SECONDARY", "TDC": "SECONDARY", "DT": "SECONDARY", "GTLB": "ENABLER"},
    "ai.software_and_data.cybersecurity": {"PANW": "CORE", "CRWD": "CORE", "FTNT": "CORE", "ZS": "CORE", "OKTA": "SECONDARY", "S": "SECONDARY", "CHKP": "SECONDARY", "TENB": "SECONDARY", "QLYS": "ENABLER", "GEN": "ENABLER"},
    "ai.software_and_data.developer_ecosystem": {"MSFT": "SECONDARY", "GTLB": "CORE", "NET": "CORE", "DDOG": "CORE", "CFLT": "CORE", "ESTC": "CORE", "MDB": "SECONDARY", "DOCN": "SECONDARY", "TWLO": "SECONDARY", "AKAM": "ENABLER"},
    "ai.applications.robotics": {"ISRG": "CORE", "ROK": "CORE", "TER": "CORE", "SYM": "CORE", "PATH": "CORE", "CGNX": "SECONDARY", "ZBRA": "SECONDARY", "HON": "SECONDARY", "EMR": "SECONDARY", "NVDA": "ENABLER"},
    "ai.applications.autonomous_systems": {"TSLA": "CORE", "MBLY": "CORE", "AUR": "CORE", "QCOM": "SECONDARY", "NVDA": "ENABLER", "AVAV": "CORE", "KTOS": "SECONDARY", "OUST": "ENABLER", "AEVA": "ENABLER", "JOBY": "SECONDARY"},
    "ai.applications.healthcare_ai": {"TEM": "CORE", "RXRX": "CORE", "SDGR": "CORE", "GH": "CORE", "GEHC": "SECONDARY", "ISRG": "SECONDARY", "NTRA": "SECONDARY", "CERT": "SECONDARY", "SOPH": "ENABLER", "BFLY": "ENABLER"},
    "ai.applications.financial_ai": {"SPGI": "CORE", "ICE": "CORE", "IBKR": "CORE", "HOOD": "CORE", "SOFI": "SECONDARY", "XYZ": "SECONDARY", "PYPL": "SECONDARY", "UPST": "ENABLER", "LMND": "ENABLER", "COIN": "SECONDARY"},
    "ai.applications.defense_ai": {"PLTR": "CORE", "AVAV": "CORE", "KTOS": "CORE", "LHX": "CORE", "NOC": "CORE", "RTX": "CORE", "LDOS": "SECONDARY", "BAH": "SECONDARY", "RCAT": "ENABLER", "CACI": "SECONDARY"},
    "ai.applications.consumer_ai": {"AAPL": "CORE", "GOOGL": "SECONDARY", "META": "CORE", "AMZN": "SECONDARY", "MSFT": "SECONDARY", "ADBE": "SECONDARY", "DUOL": "CORE", "SNAP": "ENABLER", "PINS": "ENABLER", "SPOT": "SECONDARY"},
}

_MANUAL_PURITY_OVERRIDES: dict[tuple[str, str], float] = {
    ("ai.compute.accelerators", "NVDA"): .98,
    ("ai.compute.accelerators", "AMD"): .95,
    ("ai.compute.accelerators", "ALAB"): .45,
    ("ai.compute.accelerators", "CRDO"): .45,
    ("ai.applications.robotics", "NVDA"): .35,
    ("ai.applications.autonomous_systems", "NVDA"): .4,
    ("ai.infrastructure.cloud", "MSFT"): .95,
    ("ai.infrastructure.cloud", "CRWV"): .65,
    ("ai.infrastructure.cloud", "NBIS"): .65,
    ("ai.software_and_data.developer_ecosystem", "MSFT"): .55,
    ("ai.applications.consumer_ai", "MSFT"): .45,
    ("ai.applications.consumer_ai", "GOOGL"): .7,
    ("ai.applications.consumer_ai", "AMZN"): .55,
    ("ai.power.energy_storage", "TSLA"): .55,
    ("ai.power.energy_storage", "AES"): .55,
    ("ai.infrastructure.servers", "VRT"): .55,
    ("ai.infrastructure.cooling", "VRT"): .9,
}

_MANUAL_SUB_ROLES: dict[str, dict[str, str]] = {
    "ai.compute.memory": {"MU": "memory", "SNDK": "flash_storage", "WDC": "storage", "STX": "storage", "SIMO": "controller", "RMBS": "memory_interface", "NTAP": "enterprise_storage", "PSTG": "enterprise_storage", "MRVL": "storage_connectivity", "MCHP": "controller"},
    "ai.infrastructure.data_centers": {**{ticker: "data_center_reit" for ticker in ("EQIX", "DLR", "IRM")}, **{ticker: "ai_hpc_infrastructure" for ticker in ("APLD", "NBIS", "CRWV", "IREN", "WULF")}, **{ticker: "international_data_center" for ticker in ("GDS", "VNET")}},
    "ai.power.nuclear_fuel_cycle": {**{ticker: "uranium_mining_development" for ticker in ("CCJ", "UEC", "UUUU", "NXE", "DNN", "URG", "EU")}, "LEU": "enrichment", "BWXT": "nuclear_components", "LTBR": "nuclear_fuel_technology"},
    "ai.power.energy_storage": {**{ticker: "grid_storage" for ticker in ("FLNC", "EOSE", "AES")}, "ALB": "battery_materials", **{ticker: "battery_cells_technology" for ticker in ("TSLA", "ENVX", "QS", "AMPX", "SLDP", "MVST")}},
}


def _capped_manual_weights(rows: list[dict[str, Any]]) -> list[float]:
    raw = [MANUAL_SEED_ROLE_FACTORS[row["role"]] * row["purity"] for row in rows]
    total = sum(raw) or 1.0
    weights = [value / total for value in raw]
    cap = min(.20, max(.15, 1 / len(rows)))
    for _ in range(len(rows) + 2):
        over = [index for index, value in enumerate(weights) if value > cap + 1e-12]
        if not over:
            break
        excess = sum(weights[index] - cap for index in over)
        for index in over:
            weights[index] = cap
        recipients = [index for index, value in enumerate(weights) if index not in over and value < cap - 1e-12]
        capacity = sum(cap - weights[index] for index in recipients)
        if not recipients or capacity <= 0:
            break
        for index in recipients:
            weights[index] += excess * (cap - weights[index]) / capacity
    normalizer = sum(weights) or 1.0
    return [weight / normalizer for weight in weights]


def _build_manual_seed() -> dict[str, tuple[dict[str, Any], ...]]:
    seed: dict[str, tuple[dict[str, Any], ...]] = {}
    for node_id, symbols in MANUAL_CURATED_SEED_SYMBOLS.items():
        rows: list[dict[str, Any]] = []
        overrides = _MANUAL_ROLE_OVERRIDES.get(node_id, {})
        for index, ticker in enumerate(symbols):
            role = overrides.get(ticker, MANUAL_SEED_DEFAULT_ROLES[index])
            purity = _MANUAL_PURITY_OVERRIDES.get((node_id, ticker), {"CORE": .9, "SECONDARY": .7, "ENABLER": .5}[role])
            rows.append({
                "ticker": ticker,
                "role": role,
                "purity": purity,
                "exposure_weight": MANUAL_SEED_ROLE_FACTORS[role],
                "confidence": 1.0,
                "liquidity": 1.0,
                "notes": f"{role.title()} representative in the {node_id} synthetic basket.",
                "sub_role": _MANUAL_SUB_ROLES.get(node_id, {}).get(ticker),
            })
        for row, weight in zip(rows, _capped_manual_weights(rows)):
            row["weight"] = weight
            row["role_factor"] = MANUAL_SEED_ROLE_FACTORS[row["role"]]
        seed[node_id] = tuple(rows)
    return seed


MANUAL_CURATED_SEED = _build_manual_seed()
MANUAL_CURATED_SEEDS = MANUAL_CURATED_SEED
MANUAL_SEED_UNIVERSE = {node: tuple(row["ticker"] for row in rows) for node, rows in MANUAL_CURATED_SEED.items()}
MANUAL_CURATED_SEED_UNIVERSE = MANUAL_SEED_UNIVERSE
MANUAL_SEED_MEMBERSHIPS = tuple({"node_id": node, **row} for node, rows in MANUAL_CURATED_SEED.items() for row in rows)
MANUAL_CURATED_SEED_MEMBERSHIPS = MANUAL_SEED_MEMBERSHIPS

CLASSIFICATION_SOURCE_PRIORITY = {
    MANUAL_CURATED_SEED_SOURCE: 100,
    "MANUAL": 90,
    "AI_CLASSIFIED": 80,
    "PROVIDER": 60,
    "ETF_HOLDING": 50,
    "INHERITED": 40,
}
SOURCE_PRIORITY = CLASSIFICATION_SOURCE_PRIORITY


BASE_SECTORS, BASE_GROUPS, BASE_LEAVES = _base_nodes()
BASE_TAXONOMY = BASE_SECTORS + BASE_GROUPS + BASE_LEAVES
BASE_TAXONOMY_BY_ID = {row["id"]: row for row in BASE_TAXONOMY}
BASE_TAXONOMY_BY_CODE = {row["code"]: row for row in BASE_TAXONOMY}

AI_CATEGORIES, AI_GROUPS, AI_NODES = _ai_nodes()
AI_TAXONOMY = AI_CATEGORIES + AI_GROUPS + AI_NODES
AI_TAXONOMY_BY_ID = {row["id"]: row for row in AI_TAXONOMY}


def _ai_id(category: str, group: str | None = None, node: str | None = None) -> str:
    category_id = f"ai.{_slug(category.removeprefix('AI '))}"
    if group is None:
        return category_id
    group_id = f"{category_id}.{_slug(group)}"
    if node is None:
        return group_id
    return f"{group_id}.{_slug(node)}"


def _base_id(code: str) -> str:
    return BASE_TAXONOMY_BY_CODE[code]["id"]


def _hierarchy_relations() -> list[dict[str, str]]:
    return [
        {"source_id": row["parent_id"], "target_id": row["id"], "relation": "parent"}
        for row in AI_TAXONOMY
        if row["parent_id"]
    ]


# The explicit chain is a research relationship, not a claim of fund flows.
_CHAIN = (
    (_base_id("01.01"), _ai_id("AI INFRASTRUCTURE", "Servers", "AI Servers")),
    (_ai_id("AI INFRASTRUCTURE", "Servers", "AI Servers"), _ai_id("AI INFRASTRUCTURE", "Data Centers")),
    (_ai_id("AI INFRASTRUCTURE", "Data Centers"), _ai_id("AI INFRASTRUCTURE", "Networking")),
    (_ai_id("AI INFRASTRUCTURE", "Networking"), _ai_id("AI POWER")),
    (_ai_id("AI POWER"), _ai_id("AI POWER", "Grid")),
    (_ai_id("AI POWER", "Grid"), _ai_id("AI INFRASTRUCTURE", "Cooling")),
    (_ai_id("AI INFRASTRUCTURE", "Cooling"), _ai_id("AI INFRASTRUCTURE", "Cloud")),
    (_ai_id("AI INFRASTRUCTURE", "Cloud"), _ai_id("AI SOFTWARE & DATA", "Enterprise AI")),
    (_ai_id("AI SOFTWARE & DATA", "Enterprise AI"), _ai_id("AI APPLICATIONS")),
)
AI_RELATIONS = tuple(
    _hierarchy_relations()
    + [
        {"source_id": source, "target_id": target, "relation": "downstream"}
        for source, target in _CHAIN
    ]
)


def _mapping(
    node_id: str,
    role: str,
    *,
    purity: float,
    exposure_weight: float = 1.0,
    confidence: float,
    coverage_quality: str,
    notes: str,
) -> dict[str, Any]:
    if role not in REGISTRY_ROLES:
        raise ValueError(f"invalid ETF role: {role}")
    if not 0 <= purity <= 1 or not 0 <= exposure_weight <= 1 or not 0 <= confidence <= 1:
        raise ValueError("ETF weights must be in [0, 1]")
    return {
        "node_id": node_id,
        "role": role,
        "purity": purity,
        "exposure_weight": exposure_weight,
        "confidence": confidence,
        "coverage_quality": coverage_quality,
        "notes": notes,
        "enabled": True,
    }


def _etf(
    ticker: str,
    name: str,
    *mappings: dict[str, Any],
    role: str | None = None,
    benchmark: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    mapping_rows = tuple(mappings)
    primary = mapping_rows[0] if len(mapping_rows) == 1 else None
    return {
        "ticker": ticker,
        "name": name,
        "instrument_class": "equity_etf",
        "enabled": True,
        "provider_priority": ("yfinance", "finnhub"),
        "benchmark": benchmark,
        "role": role or (primary["role"] if primary else None),
        "node_id": primary["node_id"] if primary else None,
        "purity": primary["purity"] if primary else None,
        "exposure_weight": primary["exposure_weight"] if primary else None,
        "confidence": primary["confidence"] if primary else None,
        "coverage_quality": primary["coverage_quality"] if primary else None,
        "notes": notes,
        "mappings": mapping_rows,
    }


def _market_benchmark(ticker: str) -> dict[str, Any]:
    return _etf(ticker, f"Market benchmark {ticker}", role="benchmark", benchmark="market")


def _sector_benchmark(ticker: str, code: str) -> dict[str, Any]:
    return _etf(
        ticker,
        f"Level-1 sector benchmark {ticker}",
        _mapping(
            _base_id(code),
            "primary",
            purity=.95,
            confidence=.95,
            coverage_quality="high",
            notes="Primary Level-1 sector proxy used in that sector's own Pulse.",
        ),
        _mapping(
            _base_id(code),
            "benchmark",
            purity=1.0,
            confidence=1.0,
            coverage_quality="high",
            notes="Relative-strength benchmark only; excluded from node Pulse.",
        ),
        role="benchmark",
        benchmark="sector",
    )


# The registry is keyed by ticker so the three intentional multi-node cases
# (XLE/XLU/LIT) remain one instrument with node-specific mapping rows.
ETF_REGISTRY = {
    row["ticker"]: row
    for row in (
        _market_benchmark("SPY"),
        _market_benchmark("QQQ"),
        _market_benchmark("IWM"),
        _market_benchmark("DIA"),
        _market_benchmark("RSP"),
        _market_benchmark("VTI"),
        _sector_benchmark("XLK", "01"),
        _sector_benchmark("XLC", "02"),
        _sector_benchmark("XLY", "03"),
        _sector_benchmark("XLP", "04"),
        _sector_benchmark("XLV", "05"),
        _sector_benchmark("XLF", "06"),
        _sector_benchmark("XLI", "07"),
        _sector_benchmark("XLE", "08"),
        _sector_benchmark("XLB", "09"),
        _sector_benchmark("XLU", "10"),
        _sector_benchmark("XLRE", "11"),
        _etf("SMH", "Semiconductor ETF SMH",
             _mapping(_base_id("01.01"), "primary", purity=.85, confidence=.9, coverage_quality="high", notes="Broad semiconductor proxy."),
             _mapping(_ai_id("AI COMPUTE"), "secondary", purity=.35, exposure_weight=.8, confidence=.55, coverage_quality="low", notes="Low-purity AI compute proxy."),
             _mapping(_ai_id("AI COMPUTE", "Accelerators"), "secondary", purity=.55, exposure_weight=.8, confidence=.65, coverage_quality="medium", notes="Semiconductor price proxy; constituent basket supplies AI-specific breadth.")),
        _etf("SOXX", "Semiconductor ETF SOXX",
             _mapping(_base_id("01.01"), "primary", purity=.85, confidence=.9, coverage_quality="high", notes="Broad semiconductor proxy."),
             _mapping(_ai_id("AI COMPUTE"), "secondary", purity=.35, exposure_weight=.8, confidence=.55, coverage_quality="low", notes="Low-purity AI compute proxy."),
             _mapping(_ai_id("AI COMPUTE", "Accelerators"), "secondary", purity=.55, exposure_weight=.8, confidence=.65, coverage_quality="medium", notes="Secondary semiconductor price confirmation; constituent basket supplies AI-specific breadth.")),
        _etf("XSD", "Semiconductor ETF XSD",
             _mapping(_base_id("01.01"), "secondary", purity=.7, confidence=.8, coverage_quality="medium", notes="Secondary semiconductor confirmation.")),
        _etf("SOXQ", "Semiconductor ETF SOXQ",
             _mapping(_base_id("01.01"), "secondary", purity=.7, confidence=.8, coverage_quality="medium", notes="Secondary semiconductor confirmation.")),
        _etf("SMHX", "Fabless semiconductor ETF SMHX",
             _mapping(_base_id("01.01.02"), "primary", purity=.65, confidence=.7, coverage_quality="medium", notes="Fabless proxy; holdings purity requires registry health review.")),
        _etf("IGV", "Broad software ETF IGV",
             _mapping(_base_id("01.03"), "primary", purity=.7, confidence=.8, coverage_quality="medium", notes="Broad software proxy.")),
        _etf("CLOU", "Cloud ETF CLOU",
             _mapping(_base_id("01.03.03"), "primary", purity=.65, confidence=.7, coverage_quality="medium", notes="Cloud software proxy; holdings purity review required.")),
        _etf("SKYY", "Cloud ETF SKYY",
             _mapping(_base_id("01.03.03"), "secondary", purity=.6, confidence=.65, coverage_quality="medium", notes="Cloud software proxy; holdings purity review required.")),
        _etf("WCLD", "Cloud ETF WCLD",
             _mapping(_base_id("01.03.03"), "secondary", purity=.6, confidence=.65, coverage_quality="medium", notes="Cloud software proxy; holdings purity review required.")),
        _etf("CIBR", "Cybersecurity ETF CIBR",
             _mapping(_base_id("01.03.06"), "primary", purity=.75, confidence=.8, coverage_quality="high", notes="Cybersecurity proxy.")),
        _etf("HACK", "Cybersecurity ETF HACK",
             _mapping(_base_id("01.03.06"), "secondary", purity=.7, confidence=.75, coverage_quality="medium", notes="Secondary cybersecurity confirmation.")),
        _etf("BUG", "Cybersecurity ETF BUG",
             _mapping(_base_id("01.03.06"), "secondary", purity=.7, confidence=.75, coverage_quality="medium", notes="Secondary cybersecurity confirmation.")),
        _etf("AIQ", "Broad AI theme ETF AIQ", role="reference", benchmark="ai_broad_theme", notes="Reference only; never a specific node constituent."),
        _etf("BOTZ", "Robotics ETF BOTZ",
             _mapping(_base_id("07.02.04"), "primary", purity=.7, confidence=.75, coverage_quality="medium", notes="Industrial robotics proxy."),
             _mapping(_ai_id("AI APPLICATIONS", "Robotics"), "secondary", purity=.55, confidence=.55, coverage_quality="low", notes="Broad AI robotics proxy.")),
        _etf("ROBO", "Robotics ETF ROBO",
             _mapping(_base_id("07.02.04"), "secondary", purity=.65, confidence=.7, coverage_quality="medium", notes="Secondary robotics confirmation.")),
        _etf("DTCR", "Data center REIT ETF DTCR",
             _mapping(_base_id("11.01.01"), "primary", purity=.8, confidence=.8, coverage_quality="high", notes="Data-center REIT proxy."),
             _mapping(_ai_id("AI INFRASTRUCTURE", "Data Centers"), "secondary", purity=.55, confidence=.6, coverage_quality="low", notes="Digital-infrastructure proxy.")),
        _etf("IDGT", "Digital infrastructure ETF IDGT",
             _mapping(_base_id("11.01"), "secondary", purity=.65, confidence=.7, coverage_quality="medium", notes="Digital infrastructure proxy."),
             _mapping(_ai_id("AI INFRASTRUCTURE", "Data Centers"), "secondary", purity=.45, confidence=.5, coverage_quality="low", notes="Broader digital-infrastructure proxy.")),
        _etf("NLR", "Nuclear energy chain ETF NLR",
             _mapping(_base_id("10.03"), "primary", purity=.55, confidence=.65, coverage_quality="low", notes="Broad nuclear-energy chain; not uranium mining."),
             _mapping(_ai_id("AI POWER", "Power Generation", "Nuclear"), "secondary", purity=.5, confidence=.6, coverage_quality="low", notes="Nuclear-generation proxy; not uranium mining.")),
        _etf("URA", "Uranium ETF URA",
             _mapping(_base_id("09.01.10"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Uranium mining proxy."),
             _mapping(_ai_id("AI POWER", "Nuclear Fuel Cycle", "Uranium Mining"), "primary", purity=.75, confidence=.8, coverage_quality="high", notes="Uranium fuel-cycle proxy.")),
        _etf("GRID", "Grid and electrification ETF GRID",
             _mapping(_base_id("07.03.01"), "primary", purity=.6, confidence=.7, coverage_quality="medium", notes="Grid-equipment proxy."),
             _mapping(_ai_id("AI POWER", "Grid", "Grid Infrastructure"), "primary", purity=.6, confidence=.7, coverage_quality="medium", notes="Grid infrastructure proxy.")),
        _etf("XOP", "Oil exploration and production ETF XOP",
             _mapping(_base_id("08.01.02"), "primary", purity=.75, confidence=.8, coverage_quality="medium", notes="E&P proxy; holdings purity review required.")),
        _etf("OIH", "Oilfield services ETF OIH",
             _mapping(_base_id("08.01.04"), "primary", purity=.75, confidence=.8, coverage_quality="medium", notes="Oilfield-services proxy; holdings purity review required.")),
        _etf("ICLN", "Clean energy ETF ICLN",
             _mapping(_base_id("10.04"), "secondary", purity=.45, confidence=.55, coverage_quality="low", notes="Broad renewable-generation proxy.")),
        _etf("TAN", "Solar ETF TAN",
             _mapping(_base_id("10.04.01"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Solar-generation proxy.")),
        _etf("LIT", "Battery and lithium ETF LIT",
             _mapping(_base_id("09.01.07"), "secondary", purity=.55, exposure_weight=.8, confidence=.65, coverage_quality="low", notes="Lithium-mining exposure is mixed with battery technology."),
             _mapping(_ai_id("AI POWER", "Energy Storage", "Battery"), "secondary", purity=.35, exposure_weight=.8, confidence=.5, coverage_quality="low", notes="Battery technology proxy; not pure lithium mining.")),
        _etf("COPX", "Copper miners ETF COPX",
             _mapping(_base_id("09.01.01"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Copper-equity proxy.")),
        _etf("GDX", "Gold miners ETF GDX",
             _mapping(_base_id("09.01.05"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Gold-mining equity proxy.")),
        _etf("SIL", "Silver miners ETF SIL",
             _mapping(_base_id("09.01.06"), "primary", purity=.75, confidence=.8, coverage_quality="high", notes="Silver-mining equity proxy.")),
        _etf("REMX", "Rare-earth miners ETF REMX",
             _mapping(_base_id("09.01.09"), "primary", purity=.65, confidence=.7, coverage_quality="medium", notes="Rare-earth equity proxy.")),
        _etf("SLX", "Steel ETF SLX",
             _mapping(_base_id("09.01.03"), "primary", purity=.75, confidence=.8, coverage_quality="high", notes="Steel-equity proxy.")),
        _etf("IBB", "Biotechnology ETF IBB",
             _mapping(_base_id("05.02"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Broad biotech proxy.")),
        _etf("XBI", "Biotechnology ETF XBI",
             _mapping(_base_id("05.02"), "secondary", purity=.8, confidence=.85, coverage_quality="high", notes="Equal-weight biotech confirmation.")),
        _etf("IHI", "Medical devices ETF IHI",
             _mapping(_base_id("05.03.01"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Medical-device proxy.")),
        _etf("XPH", "Pharmaceuticals ETF XPH",
             _mapping(_base_id("05.01"), "primary", purity=.7, confidence=.75, coverage_quality="medium", notes="Broad pharmaceutical proxy.")),
        _etf("KBE", "Bank ETF KBE",
             _mapping(_base_id("06.01"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Broad bank proxy.")),
        _etf("KRE", "Regional bank ETF KRE",
             _mapping(_base_id("06.01.02"), "primary", purity=.85, confidence=.9, coverage_quality="high", notes="Regional-bank proxy.")),
        _etf("KIE", "Insurance ETF KIE",
             _mapping(_base_id("06.04"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Insurance proxy.")),
        _etf("IAI", "Capital markets ETF IAI",
             _mapping(_base_id("06.02"), "primary", purity=.75, confidence=.8, coverage_quality="medium", notes="Capital-markets proxy.")),
        _etf("FINX", "FinTech ETF FINX",
             _mapping(_base_id("06.05.03"), "primary", purity=.65, confidence=.7, coverage_quality="medium", notes="FinTech-platform proxy.")),
        _etf("PAVE", "Infrastructure ETF PAVE",
             _mapping(_base_id("07.04.02"), "primary", purity=.7, confidence=.75, coverage_quality="medium", notes="Infrastructure-contractor proxy.")),
        _etf("IYT", "Transportation ETF IYT",
             _mapping(_base_id("07.05"), "primary", purity=.7, confidence=.75, coverage_quality="medium", notes="Broad transportation proxy.")),
        _etf("ITA", "Aerospace and defense ETF ITA",
             _mapping(_base_id("07.01"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Aerospace/defense proxy.")),
        _etf("PPA", "Aerospace and defense ETF PPA",
             _mapping(_base_id("07.01"), "secondary", purity=.75, confidence=.8, coverage_quality="high", notes="Secondary aerospace/defense confirmation.")),
        _etf("XRT", "Retail ETF XRT",
             _mapping(_base_id("03.02"), "primary", purity=.7, confidence=.75, coverage_quality="medium", notes="Broad retail proxy.")),
        _etf("ITB", "Homebuilders ETF ITB",
             _mapping(_base_id("03.05.01"), "primary", purity=.8, confidence=.85, coverage_quality="high", notes="Homebuilder proxy.")),
        _etf("DRIV", "EV and autonomous ETF DRIV",
             _mapping(_base_id("03.01.02"), "primary", purity=.55, confidence=.6, coverage_quality="low", notes="EV/autonomous proxy; mixed holdings.")),
        _etf("VNQ", "Broad REIT ETF VNQ",
             _mapping(_base_id("11"), "reference", purity=.55, confidence=.7, coverage_quality="medium", notes="Broad REIT reference; prefer DTCR/IDGT for digital infrastructure.")),
    )
}

ETF_SYMBOLS = tuple(ETF_REGISTRY)
ETF_MAPPINGS = tuple(
    {"ticker": ticker, **mapping}
    for ticker, row in ETF_REGISTRY.items()
    for mapping in row["mappings"]
)


def is_exposure_included(weight: float | int | None, threshold: float = THEME_INCLUSION_THRESHOLD) -> bool:
    try:
        value = float(weight)
        return math.isfinite(value) and 0 <= value <= 1 and value >= threshold
    except (TypeError, ValueError):
        return False


def pulse_mappings(row: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(mapping for mapping in row.get("mappings", ()) if mapping.get("enabled", True) and mapping.get("role") in PULSE_ROLES)


CLASSIFICATION_SEEDS = {
    "MSFT": {
        "primary_industry": _base_id("01.03.01"),
        "secondary_industries": (_base_id("01.03.03"),),
        "theme_exposures": {
            "ai.infrastructure.cloud.hyperscalers": 1.0,
            "ai.software_and_data.enterprise_ai": 0.95,
            "ai.software_and_data.ai_platforms.ai_development_platforms": 0.85,
            "ai.compute": 0.05,
        },
    },
    "SMR": {
        "primary_industry": _base_id("10.03.02"),
        "secondary_industries": (),
        "theme_exposures": {
            "ai.power": 1.0,
            "ai.power.power_generation.advanced_nuclear_smr": 1.0,
            "ai.power.nuclear_fuel_cycle.nuclear_equipment": 0.35,
        },
    },
}


__all__ = [
    "AI_CATEGORIES",
    "AI_GROUPS",
    "AI_NODES",
    "AI_RELATIONS",
    "AI_TAXONOMY",
    "AI_TAXONOMY_BY_ID",
    "BASE_GROUPS",
    "BASE_LEAVES",
    "BASE_SECTORS",
    "BASE_TAXONOMY",
    "BASE_TAXONOMY_BY_ID",
    "BASE_TAXONOMY_BY_CODE",
    "CLASSIFICATION_SEEDS",
    "CLASSIFICATION_SOURCE_PRIORITY",
    "ETF_MAPPINGS",
    "ETF_REGISTRY",
    "ETF_SYMBOLS",
    "MANUAL_CURATED_SEED",
    "MANUAL_CURATED_SEED_MEMBERSHIPS",
    "MANUAL_CURATED_SEED_SOURCE",
    "MANUAL_CURATED_SEEDS",
    "MANUAL_CURATED_SEED_SYMBOLS",
    "MANUAL_CURATED_SEED_UNIVERSE",
    "MANUAL_SEED_MEMBERSHIPS",
    "MANUAL_SEED_MIN_CONSTITUENTS",
    "MANUAL_SEED_PREFERRED_RANGE",
    "MANUAL_SEED_ROLE_FACTORS",
    "MANUAL_SEED_TARGET_CONSTITUENTS",
    "MANUAL_SEED_UNIVERSE",
    "MANUAL_SEED_VERSION",
    "PULSE_ROLES",
    "REGISTRY_ROLES",
    "SOURCE_PRIORITY",
    "THEME_INCLUSION_THRESHOLD",
    "is_exposure_included",
    "pulse_mappings",
]
