from __future__ import annotations

CATEGORY_GROUPS: dict[str, list[str]] = {
    "Home Services": [
        "roofers",
        "plumbers",
        "electricians",
        "hvac contractors",
        "garage door repair",
        "landscapers",
        "lawn care",
        "tree service",
        "fence contractors",
        "deck builders",
        "window installers",
        "door installers",
        "siding contractors",
        "gutter cleaning",
        "gutter installers",
        "painters",
        "drywall repair",
        "flooring installers",
        "tile contractors",
        "carpet cleaners",
        "house cleaners",
        "maid services",
        "pressure washing",
        "window cleaning",
        "pest control",
        "mold remediation",
        "water damage restoration",
        "fire damage restoration",
        "foundation repair",
        "basement waterproofing",
        "insulation contractors",
        "solar installers",
        "handyman services",
        "general contractors",
        "home remodelers",
        "kitchen remodelers",
        "bathroom remodelers",
        "pool cleaning",
        "pool builders",
        "chimney sweep",
        "septic services",
        "well drilling",
        "appliance repair",
        "locksmiths",
    ],
    "Health And Wellness": [
        "dentists",
        "orthodontists",
        "chiropractors",
        "physical therapists",
        "massage therapists",
        "med spas",
        "urgent care",
        "family doctors",
        "pediatricians",
        "optometrists",
        "eye care clinics",
        "hearing aid clinics",
        "mental health counselors",
        "therapists",
        "nutritionists",
        "personal trainers",
        "gyms",
        "yoga studios",
        "pilates studios",
        "martial arts schools",
        "veterinarians",
        "animal hospitals",
    ],
    "Beauty And Personal Care": [
        "barbers",
        "hair salons",
        "nail salons",
        "lash studios",
        "brow studios",
        "waxing salons",
        "tanning salons",
        "tattoo shops",
        "piercing shops",
        "skin care clinics",
        "makeup artists",
        "bridal hair and makeup",
    ],
    "Auto And Transportation": [
        "auto repair shops",
        "mechanics",
        "body shops",
        "oil change shops",
        "tire shops",
        "brake repair",
        "transmission repair",
        "auto glass repair",
        "car washes",
        "mobile detailing",
        "towing companies",
        "roadside assistance",
        "used car dealers",
        "motorcycle repair",
        "rv repair",
        "boat repair",
        "limousine services",
        "taxi services",
        "airport shuttle",
        "moving companies",
    ],
    "Food And Hospitality": [
        "restaurants",
        "pizza shops",
        "cafes",
        "coffee shops",
        "bakeries",
        "food trucks",
        "caterers",
        "bars",
        "breweries",
        "wineries",
        "ice cream shops",
        "breakfast restaurants",
        "mexican restaurants",
        "chinese restaurants",
        "bbq restaurants",
        "hotels",
        "motels",
        "bed and breakfasts",
        "event venues",
        "wedding venues",
    ],
    "Professional Services": [
        "accountants",
        "bookkeepers",
        "tax preparers",
        "insurance agents",
        "real estate agents",
        "mortgage brokers",
        "property managers",
        "law firms",
        "personal injury lawyers",
        "family lawyers",
        "estate planning attorneys",
        "criminal defense attorneys",
        "immigration lawyers",
        "financial advisors",
        "business consultants",
        "marketing agencies",
        "web designers",
        "it support",
        "computer repair",
        "printing services",
        "sign shops",
        "photographers",
        "videographers",
        "home inspectors",
        "security system installers",
    ],
    "Local Retail": [
        "florists",
        "jewelers",
        "furniture stores",
        "mattress stores",
        "thrift stores",
        "boutiques",
        "shoe stores",
        "sporting goods stores",
        "pet stores",
        "bike shops",
        "music stores",
        "smoke shops",
        "vape shops",
        "liquor stores",
        "hardware stores",
        "garden centers",
        "party supply stores",
        "toy stores",
        "bookstores",
    ],
    "Education And Childcare": [
        "daycare centers",
        "preschools",
        "tutoring centers",
        "music lessons",
        "dance studios",
        "driving schools",
        "trade schools",
        "language schools",
        "swim schools",
        "test prep tutors",
    ],
    "Pets": [
        "dog groomers",
        "pet boarding",
        "dog daycare",
        "dog trainers",
        "pet sitters",
        "mobile pet groomers",
    ],
    "Events": [
        "dj services",
        "wedding planners",
        "event planners",
        "party rentals",
        "bounce house rentals",
        "photo booth rentals",
        "catering halls",
        "wedding photographers",
        "florists wedding",
    ],
    "High Intent Emergency": [
        "emergency plumbers",
        "emergency roof repair",
        "24 hour locksmiths",
        "emergency electricians",
        "water damage restoration",
        "towing near me",
        "emergency hvac repair",
        "sewer cleaning",
        "biohazard cleanup",
    ],
}


def all_categories() -> list[str]:
    values: list[str] = []
    for categories in CATEGORY_GROUPS.values():
        values.extend(categories)
    return sorted(set(values))


def grouped_category_labels() -> list[str]:
    labels: list[str] = []
    for group, categories in CATEGORY_GROUPS.items():
        for category in categories:
            labels.append(f"{group} / {category}")
    return labels


def category_from_label(label: str) -> str:
    if " / " in label:
        return label.split(" / ", 1)[1]
    return label


# Sales-opportunity heuristic for prioritizing categories in the UI. This is not a
# claim that every business in a category has budget or will convert.
TOP_OPPORTUNITY_CATEGORIES: tuple[str, ...] = (
    "roofers",
    "hvac contractors",
    "plumbers",
    "water damage restoration",
    "foundation repair",
    "basement waterproofing",
    "general contractors",
    "home remodelers",
    "kitchen remodelers",
    "bathroom remodelers",
    "pool builders",
    "solar installers",
    "personal injury lawyers",
    "estate planning attorneys",
    "dentists",
    "orthodontists",
    "med spas",
    "sewer cleaning",
    "tree service",
)

STRONG_OPPORTUNITY_CATEGORIES: tuple[str, ...] = (
    "electricians",
    "garage door repair",
    "fence contractors",
    "deck builders",
    "siding contractors",
    "window installers",
    "pest control",
    "mold remediation",
    "fire damage restoration",
    "septic services",
    "well drilling",
    "towing companies",
    "moving companies",
    "family lawyers",
    "criminal defense attorneys",
    "immigration lawyers",
    "veterinarians",
    "animal hospitals",
    "wedding venues",
)

# Extra lucrative/high-intent categories that were missing from the original catalog.
EXTRA_OPPORTUNITY_CATEGORIES: tuple[str, ...] = (
    "concrete contractors",
    "excavation contractors",
    "sewer repair",
    "crawl space repair",
    "commercial roofing",
    "storm damage repair",
)


def opportunity_category_labels() -> list[str]:
    """Return a profit-aware picker order while preserving the full catalog."""
    existing = set(all_categories())
    top = list(dict.fromkeys([*TOP_OPPORTUNITY_CATEGORIES, *EXTRA_OPPORTUNITY_CATEGORIES]))
    strong = [item for item in STRONG_OPPORTUNITY_CATEGORIES if item not in top]
    remaining = sorted((existing | set(EXTRA_OPPORTUNITY_CATEGORIES)) - set(top) - set(strong))
    labels: list[str] = []
    labels.extend(f"Top Opportunities / {item}" for item in top)
    labels.extend(f"Strong Opportunities / {item}" for item in strong)
    labels.extend(f"All Categories / {item}" for item in remaining)
    return labels


def opportunity_reason(category: str) -> str:
    if category in TOP_OPPORTUNITY_CATEGORIES or category in EXTRA_OPPORTUNITY_CATEGORIES:
        return "High customer/job value, strong local-search intent, and a weak website can create an obvious sales case."
    if category in STRONG_OPPORTUNITY_CATEGORIES:
        return "Strong local intent and meaningful value per customer/job make digital friction commercially relevant."
    return "Opportunity varies by local demand, customer value, business activity, and the actual website gap."
