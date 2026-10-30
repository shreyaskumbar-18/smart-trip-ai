"""Add the reviewed Karnataka destination batch without changing existing rows.

This command is deliberately separate from ``seed_data``: it only creates
records that do not already exist and never updates or deletes anything.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from travel.models import Attraction, Destination


# Descriptions are factual summaries of the place, not claims about fees,
# opening hours, access, or live conditions. Numeric attraction fields not
# supplied here use the model's existing planning defaults.
DESTINATIONS = (
    ("Chikkamagaluru", "Coffee-growing hill country and Western Ghats landscapes.", "nature,adventure,relaxation"),
    ("Mangaluru", "Coastal city with beaches, temples and cultural heritage.", "nature,culture,food,history"),
    ("Udupi", "Coastal temple town with beaches and heritage sites.", "culture,history,nature,relaxation"),
    ("Hampi", "Vijayanagara-era temple and archaeological landscape.", "history,culture,heritage"),
    ("Badami", "Rock-cut temples and Chalukyan heritage in northern Karnataka.", "history,culture,heritage"),
)

ATTRACTIONS = (
    ("Chikkamagaluru", "Mullayanagiri Peak", "nature", "Mountain summit in the Western Ghats.", "mountains,viewpoint,western-ghats"),
    ("Chikkamagaluru", "Baba Budangiri", "nature", "Mountain range in the Chikkamagaluru highlands.", "mountains,western-ghats,scenic"),
    ("Chikkamagaluru", "Jhari Falls", "nature", "Waterfall in the Chikkamagaluru hill region.", "waterfall,nature,western-ghats"),
    ("Chikkamagaluru", "Hebbe Falls", "nature", "Waterfall among the forested hills of Chikkamagaluru.", "waterfall,forest,western-ghats"),
    ("Chikkamagaluru", "Hirekolale Lake", "nature", "Lake framed by hills near Chikkamagaluru.", "lake,viewpoint,western-ghats"),
    ("Mangaluru", "Panambur Beach", "nature", "Coastal beach in Mangaluru.", "beach,coast,sunset"),
    ("Mangaluru", "Tannirbhavi Beach", "nature", "Coastal beach near Mangaluru.", "beach,coast,walking"),
    ("Mangaluru", "Kudroli Gokarnath Temple", "culture", "Temple complex and cultural landmark in Mangaluru.", "temple,architecture,culture"),
    ("Mangaluru", "Mangaladevi Temple", "culture", "Temple and heritage landmark associated with Mangaluru.", "temple,heritage,culture"),
    ("Mangaluru", "St Aloysius Chapel", "history", "Historic chapel noted for its painted interiors.", "heritage,architecture,art"),
    ("Udupi", "Sri Krishna Matha", "culture", "Temple and monastic complex in Udupi.", "temple,pilgrimage,heritage"),
    ("Udupi", "Malpe Beach", "nature", "Coastal beach near Udupi.", "beach,coast,relaxation"),
    ("Udupi", "St Mary's Island", "nature", "Offshore island group known for columnar rock formations.", "island,geology,coast"),
    ("Udupi", "Kaup Lighthouse", "history", "Coastal lighthouse and landmark near Udupi.", "lighthouse,coast,heritage"),
    ("Hampi", "Virupaksha Temple", "history", "Historic temple within the Hampi World Heritage landscape.", "temple,heritage,architecture"),
    ("Hampi", "Vittala Temple Complex", "history", "Temple complex known for Vijayanagara architecture.", "temple,heritage,architecture"),
    ("Hampi", "Hampi Bazaar", "history", "Historic market street within the Hampi archaeological landscape.", "heritage,market,architecture"),
    ("Hampi", "Hemakuta Hill Temples", "history", "Group of historic shrines and mandapas on Hemakuta Hill.", "temple,heritage,hill"),
    ("Badami", "Badami Cave Temples", "history", "Rock-cut temple complex in Badami's sandstone cliffs.", "cave-temple,heritage,architecture"),
    ("Badami", "Agastya Lake", "nature", "Historic lake below the Badami cave-temple cliffs.", "lake,heritage,landscape"),
    ("Badami", "Bhutanatha Temples", "history", "Sandstone temples beside Agastya Lake.", "temple,heritage,architecture"),
)

# Coordinates are included only for named sites with reliable point references.
# Sources: NCSCM (St Mary's Island), Sagarmala (Kaup Lighthouse), UNESCO/ASI
# Hampi Circle (Virupaksha, Vittala and Hemakuta). Other coordinates stay NULL.
ATTRACTION_COORDS = {
    ("Udupi", "St Mary's Island"): (13.377000, 74.674900),
    ("Udupi", "Kaup Lighthouse"): (13.223333, 74.736667),
    ("Hampi", "Virupaksha Temple"): (15.336667, 76.453333),
    ("Hampi", "Vittala Temple Complex"): (15.342304, 76.475259),
    ("Hampi", "Hemakuta Hill Temples"): (15.334488, 76.458637),
}


def _key(value):
    return " ".join(value.casefold().split())


class Command(BaseCommand):
    help = "Add missing reviewed Karnataka destinations and attractions without updating existing records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report records that would be created or skipped without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        counts = {"destinations_created": 0, "attractions_created": 0, "skipped": 0}
        actions = []
        create_destinations = []
        create_attractions = []

        # Resolve all targets before writing so an ambiguous existing
        # destination cannot result in attractions being attached arbitrarily.
        destinations_by_name = {}
        for name, _description, _best_for in DESTINATIONS:
            matches = [d for d in Destination.objects.all() if _key(d.name) == _key(name)
                       and _key(d.state) == _key("Karnataka")]
            destinations_by_name[name] = matches

        for name, description, best_for in DESTINATIONS:
            matches = destinations_by_name[name]
            if len(matches) > 1:
                actions.append((f"destination {name}", "SKIP", "multiple matching Karnataka rows"))
                counts["skipped"] += 1
                for attraction in (row for row in ATTRACTIONS if row[0] == name):
                    actions.append((f"attraction {attraction[1]}", "SKIP", "destination match is ambiguous"))
                    counts["skipped"] += 1
                continue

            destination = matches[0] if matches else None
            if destination is None:
                actions.append((f"destination {name}", "CREATE", "missing"))
                counts["destinations_created"] += 1
                create_destinations.append((name, description, best_for))
            else:
                actions.append((f"destination {name}", "SKIP", "already exists; left unchanged"))
                counts["skipped"] += 1

            existing_attractions = list(destination.attractions.all()) if destination else []

            for row_destination, attraction_name, category, description, tags in (r for r in ATTRACTIONS if r[0] == name):
                if any(_key(item.name) == _key(attraction_name) for item in existing_attractions):
                    actions.append((f"attraction {attraction_name}", "SKIP", "already exists; left unchanged"))
                    counts["skipped"] += 1
                    continue
                actions.append((f"attraction {attraction_name}", "CREATE", "missing"))
                counts["attractions_created"] += 1
                create_attractions.append((row_destination, attraction_name, category, description, tags))

        for label, action, detail in actions:
            self.stdout.write(f"{action}: {label} ({detail})")

        if not dry_run:
            try:
                with transaction.atomic():
                    destination_objects = {
                        name: matches[0]
                        for name, matches in destinations_by_name.items()
                        if len(matches) == 1
                    }
                    for name, description, best_for in create_destinations:
                        destination_objects[name] = Destination.objects.create(
                            name=name, state="Karnataka", description=description, best_for=best_for
                        )
                    for destination_name, attraction_name, category, description, tags in create_attractions:
                        destination = destination_objects.get(destination_name)
                        if destination is None:
                            raise ValueError(f"No unambiguous destination for {attraction_name}.")
                        create_fields = {
                            "destination": destination,
                            "name": attraction_name,
                            "category": category,
                            "description": description,
                            "tags": tags,
                        }
                        coords = ATTRACTION_COORDS.get((destination_name, attraction_name))
                        if coords:
                            create_fields["latitude"], create_fields["longitude"] = coords
                        Attraction.objects.create(**create_fields)
            except Exception as exc:
                raise CommandError(
                    f"Additive batch failed and was rolled back: failed=1, "
                    f"destinations_created=0, attractions_created=0, skipped={counts['skipped']}."
                ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Summary: destinations_created={counts['destinations_created']}, "
                f"attractions_created={counts['attractions_created']}, "
                f"skipped={counts['skipped']}, failed=0, dry_run={str(dry_run).lower()}"
            )
        )
