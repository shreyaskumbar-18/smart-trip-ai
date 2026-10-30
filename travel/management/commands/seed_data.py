from django.core.management.base import BaseCommand
from travel.models import Destination,Attraction

DATA=[
("Bengaluru","Karnataka","Technology, heritage, food and urban parks.","https://images.unsplash.com/photo-1596176530529-78163a4f7af2",2200,"culture,food,shopping,nature",4.6,78,82,85,
[("Cubbon Park","nature","Central green space for walking.",0,2,25,88,55,"nature,relaxation"),
("Bangalore Palace","history","Historic royal architecture.",500,2,50,70,45,"history,culture"),
("VV Puram Food Street","food","Street food experience.",500,2,65,65,40,"food,culture"),
("Lalbagh","nature","Botanical garden.",50,2.5,35,90,60,"nature,plants")]),
("Goa","Goa","Beaches, heritage, food and adventure.","https://images.unsplash.com/photo-1512343879784-a960bf40e7f2",2800,"nature,food,adventure,relaxation",4.7,72,74,82,
[("Baga Beach","nature","Popular coastal experience.",0,3,80,60,35,"nature,beach"),
("Fort Aguada","history","Historic coastal fort.",50,1.5,45,76,50,"history,culture"),
("Dudhsagar Falls","adventure","Waterfall and nature excursion.",1500,6,55,82,72,"adventure,nature"),
("Fontainhas","culture","Portuguese-era heritage quarter.",0,2,35,85,78,"culture,hidden")]),
("Mysuru","Karnataka","Palaces, gardens, culture and food.","https://images.unsplash.com/photo-1600112356915-089abb8fc5c0",1800,"history,culture,food",4.5,83,80,88,
[("Mysore Palace","history","Royal palace.",200,2,65,70,45,"history,culture"),
("Chamundi Hill","culture","Hilltop temple and city views.",0,2,35,86,55,"culture,nature"),
("Brindavan Gardens","nature","Landscaped gardens.",100,2.5,55,82,60,"nature"),
("Devaraja Market","shopping","Traditional market.",0,2,65,75,70,"shopping,food")]),
("Manali","Himachal Pradesh","Mountains, adventure and relaxation.","https://images.unsplash.com/photo-1548013146-72479768bada",2600,"nature,adventure,relaxation",4.6,79,77,80,
[("Solang Valley","adventure","Mountain activities.",800,4,70,72,60,"adventure,nature"),
("Hadimba Temple","culture","Forest temple.",0,1.5,40,88,70,"culture,nature"),
("Old Manali","food","Cafes and local shops.",500,2.5,55,72,68,"food,shopping"),
("Jogini Falls","nature","Quieter waterfall trail.",100,3,25,91,90,"nature,hidden")]),
("Jaipur","Rajasthan","Forts, palaces, markets and cuisine.","https://images.unsplash.com/photo-1599661046289-e31897846e41",2400,"history,culture,food,shopping",4.7,76,69,84,
[("Amber Fort","history","Hill fort and palace.",550,3,70,70,45,"history"),
("Hawa Mahal","history","Historic city landmark.",200,1.5,75,68,35,"history,culture"),
("City Palace","culture","Royal complex and museums.",500,2.5,60,74,50,"culture,history"),
("Panna Meena Stepwell","history","Architectural stepwell with fewer crowds.",50,1.5,25,88,88,"history,hidden")]),
("Munnar","Kerala","Tea plantations, hills and nature.","https://images.unsplash.com/photo-1602216056096-3b40cc0c9944",2100,"nature,relaxation,adventure",4.6,91,90,86,
[("Tea Gardens","nature","Scenic plantation walks.",200,3,40,92,65,"nature"),
("Eravikulam National Park","nature","Mountain biodiversity.",200,4,50,95,62,"nature,adventure"),
("Mattupetty Dam","relaxation","Lake and hill views.",100,2,45,88,65,"relaxation,nature"),
("Kolukkumalai Sunrise","nature","High-altitude sunrise experience.",500,4,20,96,94,"nature,hidden,adventure")]),
# New rows use existing model defaults for estimated cost and neutral metrics;
# the cost value is not a published ticket or access fee.
("Chikkamagaluru","Karnataka","Coffee-growing hill country and Western Ghats landscapes.","",2000,"nature,adventure,relaxation",4.5,70,50,80,
[("Mullayanagiri Peak","nature","Mountain summit and Western Ghats viewpoints.",300,3,50,70,50,"mountains,viewpoint,western-ghats"),
("Baba Budangiri","nature","Mountain range with scenic highland landscapes.",300,2,50,70,50,"mountains,western-ghats,scenic"),
("Jhari Falls","nature","Waterfall in the Chikkamagaluru hill region.",300,3,50,70,50,"waterfall,nature,western-ghats"),
("Hebbe Falls","nature","Waterfall set among the forested hills of Chikkamagaluru.",300,4,50,70,50,"waterfall,forest,western-ghats"),
("Hirekolale Lake","nature","Reservoir framed by the hills near Chikkamagaluru.",300,1.5,50,70,50,"lake,viewpoint,western-ghats")]),
("Mangaluru","Karnataka","Coastal city with beaches, temples and cultural heritage.","",2000,"nature,culture,food,history",4.5,70,50,80,
[("Panambur Beach","nature","Popular coastal beach in Mangaluru.",300,2.5,50,70,50,"beach,coast,sunset"),
("Tannirbhavi Beach","nature","Coastal beach and green shoreline near Mangaluru.",300,2,50,70,50,"beach,coast,walking"),
("Kudroli Gokarnath Temple","culture","Temple complex and cultural landmark in Mangaluru.",300,1.5,50,70,50,"temple,architecture,culture"),
("Mangaladevi Temple","culture","Historic temple associated with the city of Mangaluru.",300,1,50,70,50,"temple,heritage,culture"),
("St Aloysius Chapel","history","Historic chapel known for its painted interiors.",300,1.5,50,70,50,"heritage,architecture,art")]),
("Udupi","Karnataka","Coastal temple town with beaches and heritage sites.","",2000,"culture,history,nature,relaxation",4.5,70,50,80,
[("Sri Krishna Matha","culture","Temple and monastic complex in the heart of Udupi.",300,1.5,50,70,50,"temple,pilgrimage,heritage"),
("Malpe Beach","nature","Coastal beach near Udupi.",300,2,50,70,50,"beach,coast,relaxation"),
("St Mary's Island","nature","Offshore island group known for columnar rock formations.",300,2,50,70,50,"island,geology,coast"),
("Kaup Lighthouse","history","Coastal lighthouse and landmark near Udupi.",300,1,50,70,50,"lighthouse,coast,heritage")]),
("Hampi","Karnataka","Vijayanagara-era temple and archaeological landscape.","",2000,"history,culture,heritage",4.5,70,50,80,
[("Virupaksha Temple","history","Historic temple within the Hampi World Heritage landscape.",300,2,50,70,50,"temple,heritage,architecture"),
("Vittala Temple Complex","history","Monumental temple complex known for its Vijayanagara architecture.",300,2.5,50,70,50,"temple,heritage,architecture"),
("Hampi Bazaar","history","Historic market street within the Hampi archaeological landscape.",300,1.5,50,70,50,"heritage,market,architecture"),
("Hemakuta Hill Temples","history","Group of historic shrines and mandapas on Hemakuta Hill.",300,1.5,50,70,50,"temple,heritage,hill")]),
("Badami","Karnataka","Rock-cut temples and Chalukyan heritage in northern Karnataka.","",2000,"history,culture,heritage",4.5,70,50,80,
[("Badami Cave Temples","history","Rock-cut temple complex in the sandstone cliffs of Badami.",300,2,50,70,50,"cave-temple,heritage,architecture"),
("Agastya Lake","nature","Historic lake below the Badami cave-temple cliffs.",300,1.5,50,70,50,"lake,heritage,landscape"),
("Bhutanatha Temples","history","Group of sandstone temples beside Agastya Lake.",300,1.5,50,70,50,"temple,heritage,architecture")])
]

ATTRACTION_COORDS = {
    ("Bengaluru", "Cubbon Park"): (12.9763, 77.5929),
    ("Bengaluru", "Bangalore Palace"): (13.0035, 77.5891),
    ("Bengaluru", "VV Puram Food Street"): (12.949, 77.575),
    ("Bengaluru", "Lalbagh"): (12.9507, 77.5848),
    ("Goa", "Baga Beach"): (15.5557, 73.7517),
    ("Goa", "Fort Aguada"): (15.492, 73.773),
    ("Goa", "Dudhsagar Falls"): (15.3144, 74.314),
    ("Goa", "Fontainhas"): (15.4989, 73.8278),
    ("Mysuru", "Mysore Palace"): (12.3052, 76.6552),
    ("Mysuru", "Chamundi Hill"): (12.2921, 76.665),
    ("Mysuru", "Brindavan Gardens"): (12.4244, 76.572),
    ("Mysuru", "Devaraja Market"): (12.3122, 76.654),
    ("Manali", "Solang Valley"): (32.316, 77.155),
    ("Manali", "Hadimba Temple"): (32.2432, 77.1735),
    ("Manali", "Old Manali"): (32.248, 77.179),
    ("Manali", "Jogini Falls"): (32.2825, 77.214),
    ("Jaipur", "Amber Fort"): (26.9855, 75.8513),
    ("Jaipur", "Hawa Mahal"): (26.9239, 75.8267),
    ("Jaipur", "City Palace"): (26.9258, 75.8237),
    ("Jaipur", "Panna Meena Stepwell"): (26.936, 75.8425),
    ("Munnar", "Tea Gardens"): (10.0889, 77.0595),
    ("Munnar", "Eravikulam National Park"): (10.2013, 77.0475),
    ("Munnar", "Mattupetty Dam"): (10.1067, 77.1275),
    ("Munnar", "Kolukkumalai Sunrise"): (10.046, 77.242),
    # Governmental geographic references: NCSCM, Sagarmala, UNESCO and ASI Hampi Circle.
    ("Udupi", "St Mary's Island"): (13.377000, 74.674900),
    ("Udupi", "Kaup Lighthouse"): (13.223333, 74.736667),
    ("Hampi", "Virupaksha Temple"): (15.336667, 76.453333),
    ("Hampi", "Vittala Temple Complex"): (15.342304, 76.475259),
    ("Hampi", "Hemakuta Hill Temples"): (15.334488, 76.458637),
}

class Command(BaseCommand):
    help="Load SmartTrip AI sample data"
    def handle(self,*args,**kwargs):
        for row in DATA:
            name,state,desc,img,cost,best,rating,sustain,hidden,safety,atts=row
            d,_=Destination.objects.update_or_create(name=name,defaults={"state":state,"description":desc,"image_url":img,
                "average_daily_cost":cost,"best_for":best,"rating":rating,"sustainability_score":sustain,
                "hidden_gem_score":hidden,"safety_score":safety})
            for a in atts:
                an,cat,ad,c,dur,crowd,ss,hs,tags=a
                attraction_defaults = {
                    "category": cat,
                    "description": ad,
                    "estimated_cost": c,
                    "duration_hours": dur,
                    "crowd_level": crowd,
                    "sustainability_score": ss,
                    "hidden_gem_score": hs,
                    "tags": tags,
                }
                coordinates = ATTRACTION_COORDS.get((name, an))
                if coordinates is not None:
                    attraction_defaults["latitude"], attraction_defaults["longitude"] = coordinates
                Attraction.objects.update_or_create(
                    destination=d,
                    name=an,
                    defaults=attraction_defaults,
                )
        self.stdout.write(self.style.SUCCESS("SmartTrip AI data loaded."))
