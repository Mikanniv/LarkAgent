import uuid
import math
from memory.db import collection


def create_memory(
        document,
        date,
        timestamp,
        user,
        type,
        source,
        has_emotion,
        valence,
        arousal,
        confidence,
        importance,
        user_id=None,
        text_available=None,
        audio_available=None,
        video_available=None,
):
    metadata = {
        'date': date,
        'timestamp': timestamp,
        'user': user,
        'type': type,
        'source': source,
        'has_emotion': has_emotion,
        'confidence': confidence,
        'importance': importance,
    }
    if user_id is not None:
        metadata['user_id'] = user_id
    if has_emotion:
        metadata['valence'] = valence
        metadata['arousal'] = arousal
    if text_available is not None:
        metadata['text_available'] = text_available
    if audio_available is not None:
        metadata['audio_available'] = audio_available
    if video_available is not None:
        metadata['video_available'] = video_available

    return {
        'document': document,
        'metadata': metadata,
    }

def add_memory(memory):
    collection.add(
        documents=[memory['document']],
        metadatas=[memory['metadata']],
        ids=[str(uuid.uuid4())]
    )

# 召回记忆
def recall(query, k=3):
    results = collection.query(
        query_texts=[query],
        n_results=k
    )
    return results


def decay(importance, delta_time):
    return importance*math.exp(delta_time*(1-importance))