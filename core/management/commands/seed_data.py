from django.core.management.base import BaseCommand
from core.models import Destination, Place, Hotel

DESTINATIONS = [
    {'name':'Bengaluru','city':'Bengaluru','state':'Karnataka','description':'India\'s technology hub with parks, museums, food and heritage sites.','latitude':12.9716,'longitude':77.5946,'category':'City','rating':4.5},
    {'name':'Mysuru','city':'Mysuru','state':'Karnataka','description':'Heritage city known for Mysore Palace, markets and cultural attractions.','latitude':12.2958,'longitude':76.6394,'category':'Heritage','rating':4.6},
    {'name':'Coorg','city':'Madikeri','state':'Karnataka','description':'Hill destination with coffee estates, waterfalls and nature experiences.','latitude':12.4244,'longitude':75.7382,'category':'Nature','rating':4.7},
    {'name':'Hampi','city':'Hosapete','state':'Karnataka','description':'UNESCO World Heritage landscape filled with Vijayanagara-era ruins and temples.','latitude':15.3350,'longitude':76.4600,'category':'Heritage','rating':4.8},
    {'name':'Gokarna','city':'Gokarna','state':'Karnataka','description':'Coastal destination with beaches, temples and relaxed travel experiences.','latitude':14.5479,'longitude':74.3188,'category':'Beach','rating':4.6},
]

PLACES = {
    'Bengaluru': [('Lalbagh Botanical Garden','Nature',12.9507,77.5848,30,2.0,4.6),('Bangalore Palace','History',12.9987,77.5920,450,1.5,4.4),('Visvesvaraya Museum','Culture',12.9750,77.5963,100,2.0,4.5),('Cubbon Park','Nature',12.9763,77.5929,0,1.5,4.5),('Commercial Street','Shopping',12.9822,77.6081,0,2.0,4.3)],
    'Mysuru': [('Mysore Palace','History',12.3052,76.6552,100,2.0,4.8),('Chamundi Hill','Nature',12.2920,76.6730,0,2.0,4.7),('Devaraja Market','Shopping',12.3072,76.6497,0,1.5,4.3),('Railway Museum','Culture',12.3148,76.6403,50,1.5,4.4),('Karanji Lake','Nature',12.3047,76.6808,30,2.0,4.5)],
    'Coorg': [('Abbey Falls','Nature',12.4580,75.7244,40,2.0,4.6),('Raja Seat','Photography',12.4244,75.7382,20,1.0,4.5),('Madikeri Fort','History',12.4258,75.7382,0,1.5,4.4),('Coffee Estate Tour','Food',12.4070,75.7370,500,3.0,4.7),('Omkareshwara Temple','Culture',12.4208,75.7397,0,1.0,4.5)],
    'Hampi': [('Virupaksha Temple','History',15.3350,76.4600,0,2.0,4.8),('Vijaya Vittala Temple','History',15.3146,76.4760,40,2.5,4.9),('Hampi Bazaar','Shopping',15.3355,76.4617,0,1.5,4.4),('Lotus Mahal','Culture',15.3282,76.4447,40,1.5,4.7),('Matanga Hill','Photography',15.3294,76.4660,0,2.0,4.7)],
    'Gokarna': [('Om Beach','Beaches',14.5137,74.3188,0,2.5,4.7),('Kudle Beach','Beaches',14.5317,74.3149,0,2.5,4.6),('Mahabaleshwar Temple','Culture',14.5432,74.3180,0,1.5,4.6),('Yana Cave Day Trip','Adventure',14.5450,74.5480,80,4.0,4.5),('Gokarna Main Market','Shopping',14.5479,74.3188,0,1.5,4.2)],
}

class Command(BaseCommand):
    help = 'Seed SmartTrip AI with demo destinations, places and hotels.'

    def handle(self, *args, **options):
        for data in DESTINATIONS:
            dest, _ = Destination.objects.update_or_create(name=data['name'], defaults=data)
            for name, category, lat, lng, fee, hours, rating in PLACES[data['name']]:
                Place.objects.update_or_create(name=name, destination=dest, defaults={
                    'description': f'{name} in {dest.name}.', 'category': category,
                    'latitude': lat, 'longitude': lng, 'entry_fee': fee,
                    'estimated_visit_time': hours, 'rating': rating,
                })
            for suffix, price, rating in [('Comfort Stay', 1800, 4.2), ('City View Hotel', 2800, 4.4), ('Premium Resort', 4500, 4.7)]:
                Hotel.objects.update_or_create(name=f'{dest.name} {suffix}', destination=dest, defaults={
                    'description': f'A demo accommodation option in {dest.name}.',
                    'price_per_night': price, 'rating': rating,
                    'latitude': dest.latitude, 'longitude': dest.longitude,
                    'facilities': 'WiFi, Parking, Breakfast',
                })
        self.stdout.write(self.style.SUCCESS('SmartTrip demo data seeded successfully.'))
