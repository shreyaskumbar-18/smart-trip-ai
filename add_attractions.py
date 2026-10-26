
import os
import django

# Configure Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smarttrip.settings")
django.setup()

from travel.models import Destination, Attraction


# Six new attractions for each destination.
# Bengaluru already has 10 attractions.
NEW_ATTRACTIONS = {
    "Goa": [
        ("Chapora Fort", "Historical", "Historic fort overlooking the Chapora River and coastline.", 50, 2.0, 45, 75, "history,fort,viewpoint"),
        ("Divar Island", "Nature", "Peaceful island known for village scenery and countryside.", 100, 3.0, 25, 85, "nature,island,hidden-gem"),
        ("Netravali Wildlife Sanctuary", "Nature", "Forest sanctuary with rich biodiversity and natural scenery.", 100, 4.0, 35, 90, "nature,wildlife,forest"),
        ("Reis Magos Fort", "Historical", "Restored heritage fort overlooking the Mandovi River.", 100, 1.5, 40, 75, "history,fort,heritage"),
        ("Butterfly Beach", "Beach", "Small scenic beach surrounded by greenery.", 0, 2.0, 35, 85, "beach,nature,hidden-gem"),
        ("Arvalem Waterfalls", "Nature", "Waterfall surrounded by greenery in North Goa.", 0, 2.0, 40, 85, "waterfall,nature"),
    ],
    "Mysuru": [
        ("Chamundi Hill", "Nature", "Hilltop destination with city views and the Chamundeshwari Temple.", 0, 2.0, 55, 70, "hill,temple,viewpoint"),
        ("Jaganmohan Palace", "Museum", "Historic palace housing an art gallery and cultural collections.", 100, 2.0, 35, 70, "museum,art,history"),
        ("Karanji Lake", "Nature", "Urban lake with birdwatching opportunities and walking areas.", 50, 2.0, 35, 85, "lake,birds,nature"),
        ("Rail Museum Mysuru", "Museum", "Railway museum featuring historic locomotives and exhibits.", 50, 1.5, 25, 70, "museum,railway,history"),
        ("Kukkarahalli Lake", "Nature", "Popular lake for peaceful walks and birdwatching.", 0, 1.5, 35, 85, "lake,walking,birds"),
        ("Regional Museum of Natural History", "Museum", "Educational museum focused on nature and biodiversity.", 0, 2.0, 25, 80, "museum,nature,education"),
    ],
    "Manali": [
        ("Jogini Waterfall", "Nature", "Scenic waterfall reached by a nature walk near Vashisht.", 0, 3.0, 35, 90, "waterfall,trek,nature"),
        ("Naggar Castle", "Historical", "Traditional Himachali castle with mountain views.", 100, 1.5, 35, 75, "history,architecture,mountains"),
        ("Vashisht Hot Springs", "Nature", "Natural hot spring area near Vashisht village.", 0, 1.5, 40, 70, "hot-springs,village,nature"),
        ("Himalayan Nyingmapa Monastery", "Cultural", "Buddhist monastery known for its peaceful atmosphere.", 0, 1.0, 35, 80, "monastery,culture,peaceful"),
        ("Van Vihar", "Nature", "Green park with trees and walking paths in Manali.", 50, 1.5, 45, 80, "park,forest,walking"),
        ("Hampta Valley Viewpoint", "Nature", "Mountain scenery and valley views in the Manali region.", 0, 2.0, 25, 85, "mountains,valley,nature"),
    ],
    "Jaipur": [
        ("Panna Meena ka Kund", "Historical", "Historic stepwell known for its symmetrical stairways.", 0, 1.0, 35, 75, "stepwell,history,architecture"),
        ("Gaitor Ki Chhatriyan", "Historical", "Royal cenotaphs featuring detailed stone carvings.", 50, 1.5, 25, 75, "heritage,architecture,history"),
        ("Anokhi Museum of Hand Printing", "Museum", "Museum exploring traditional block printing and textiles.", 100, 1.5, 30, 80, "museum,textiles,craft"),
        ("Jawahar Kala Kendra", "Cultural", "Arts centre hosting exhibitions and cultural activities.", 0, 2.0, 35, 80, "art,culture,architecture"),
        ("Sisodia Rani Garden", "Garden", "Historic terraced garden with fountains and painted pavilions.", 50, 1.5, 30, 75, "garden,history,nature"),
        ("Central Park Jaipur", "Nature", "Large city park with walking paths and open green spaces.", 0, 1.5, 45, 80, "park,walking,nature"),
    ],
    "Munnar": [
        ("Anamudi Peak Viewpoint", "Nature", "Mountain scenery in the region surrounding Anamudi Peak.", 0, 2.0, 25, 90, "mountains,viewpoint,nature"),
        ("Blossom Hydel Park", "Garden", "Landscaped park with gardens and recreational areas.", 50, 1.5, 40, 75, "garden,park,nature"),
        ("Lockhart Gap", "Nature", "Scenic mountain viewpoint with misty valley landscapes.", 0, 1.5, 25, 90, "viewpoint,mountains,hidden-gem"),
        ("Chithirapuram", "Cultural", "Quiet hill settlement surrounded by tea plantations.", 0, 2.0, 25, 85, "village,tea,nature"),
        ("Pothamedu Viewpoint", "Nature", "Viewpoint overlooking tea, coffee and cardamom plantations.", 0, 1.0, 35, 85, "viewpoint,tea,mountains"),
        ("Carmelagiri Elephant Park", "Wildlife", "Tourist attraction offering elephant-related experiences.", 500, 1.5, 45, 50, "elephants,wildlife,park"),
    ],
}


def main():
    print("\nStarting attraction database update...\n")

    total_added = 0

    for destination_name, attractions in NEW_ATTRACTIONS.items():
        try:
            destination = Destination.objects.get(name__iexact=destination_name)
        except Destination.DoesNotExist:
            print(f"WARNING: Destination '{destination_name}' was not found.")
            continue

        added_for_destination = 0

        for (
            name,
            category,
            description,
            cost,
            duration,
            crowd,
            sustainability,
            tags,
        ) in attractions:

            _, created = Attraction.objects.get_or_create(
                destination=destination,
                name=name,
                defaults={
                    "category": category,
                    "description": description,
                    "estimated_cost": cost,
                    "duration_hours": duration,
                    "crowd_level": crowd,
                    "sustainability_score": sustainability,
                    "hidden_gem_score": 80 if "hidden-gem" in tags else 50,
                    "tags": tags,
                },
            )

            if created:
                added_for_destination += 1
                total_added += 1

        print(
            f"{destination_name}: "
            f"{added_for_destination} new attractions added"
        )

    print("\n========== DATABASE SUMMARY ==========")
    print(f"New attractions added: {total_added}")
    print(f"Total attractions in database: {Attraction.objects.count()}")

    print("\nAttractions per destination:")

    for destination in Destination.objects.all():
        print(
            f"{destination.name}: "
            f"{destination.attractions.count()} attractions"
        )

    print("\nDatabase update finished!")


if __name__ == "__main__":
    main()
