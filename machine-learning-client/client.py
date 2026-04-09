'''
Script that connects to Database 
'''

from datetime import datetime
from pymongo import MongoClient

client = MongoClient("mongodb://admin:secret@mongo:27017/?authSource=admin")
db = client['mydatabase']
collection = db['records']

result = {
    'timestamp': datetime.now(),
    'label': 'test_detection',
    'confidence': 0.95
}

collection.insert_one(result)
print("Result inserted into MongoDB")
