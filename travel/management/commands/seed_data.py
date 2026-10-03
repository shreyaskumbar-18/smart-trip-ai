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
("Kolukkumalai Sunrise","nature","High-altitude sunrise experience.",500,4,20,96,94,"nature,hidden,adventure")])
]

ATTRACTION_COORDS = {'Cubbon Park': (12.9763, 77.5929), 'Bangalore Palace': (13.0035, 77.5891), 'VV Puram Food Street': (12.949, 77.575), 'Lalbagh': (12.9507, 77.5848), 'Baga Beach': (15.5557, 73.7517), 'Fort Aguada': (15.492, 73.773), 'Dudhsagar Falls': (15.3144, 74.314), 'Fontainhas': (15.4989, 73.8278), 'Mysore Palace': (12.3052, 76.6552), 'Chamundi Hill': (12.2921, 76.665), 'Brindavan Gardens': (12.4244, 76.572), 'Devaraja Market': (12.3122, 76.654), 'Solang Valley': (32.316, 77.155), 'Hadimba Temple': (32.2432, 77.1735), 'Old Manali': (32.248, 77.179), 'Jogini Falls': (32.2825, 77.214), 'Amber Fort': (26.9855, 75.8513), 'Hawa Mahal': (26.9239, 75.8267), 'City Palace': (26.9258, 75.8237), 'Panna Meena Stepwell': (26.936, 75.8425), 'Tea Gardens': (10.0889, 77.0595), 'Eravikulam National Park': (10.2013, 77.0475), 'Mattupetty Dam': (10.1067, 77.1275), 'Kolukkumalai Sunrise': (10.046, 77.242)}

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
                Attraction.objects.update_or_create(
                    destination=d,
                    name=an,
                    defaults={
                        "category": cat,
                        "description": ad,
                        "estimated_cost": c,
                        "duration_hours": dur,
                        "crowd_level": crowd,
                        "sustainability_score": ss,
                        "hidden_gem_score": hs,
                        "tags": tags,
                        "latitude": ATTRACTION_COORDS.get(an, (None, None))[0],
                        "longitude": ATTRACTION_COORDS.get(an, (None, None))[1],
                    },
                )
        self.stdout.write(self.style.SUCCESS("SmartTrip AI data loaded."))
