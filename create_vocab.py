# create_vocab.py
import boto3, time

region = "us-east-1"   # use same region in aws configure and config.py
vocab_name = "racetrack-classes"
phrases = [
    "SuperPro",
    "SPro",
    "SuPro",
    "Sportsman",
    "Amateur",
    "Tothelanes",
    "standby",
    "OnStandby",
    "general"    
]

t = boto3.client('transcribe', region_name=region)
print("Creating vocabulary:", vocab_name)
t.create_vocabulary(VocabularyName=vocab_name, LanguageCode='en-US', Phrases=phrases)

# poll status
while True:
    resp = t.get_vocabulary(VocabularyName=vocab_name)
    state = resp.get('VocabularyState')
    print("Vocabulary state:", state)
    if state in ('READY','FAILED'):
        print(resp)
        break
    time.sleep(2)
