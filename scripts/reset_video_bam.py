import os
from google.cloud import firestore
from google.cloud import storage

db = firestore.Client(project="helixstreet-agent")
storage_client = storage.Client(project="helixstreet-agent")

# Delete twin
db.collection("digital_twins").document("video-bam").delete()

# Delete audit ledger entries for video-bam
docs = db.collection("audit_ledger").where("sample_id", "==", "video-bam").stream()
for doc in docs:
    doc.reference.delete()

# Delete event idempotency records for video-bam
docs = db.collection("events").where("object", ">=", "uploads/video-bam/").where("object", "<=", "uploads/video-bam/\uf8ff").stream()
for doc in docs:
    doc.reference.delete()

print("Firestore state for video-bam reset.")
