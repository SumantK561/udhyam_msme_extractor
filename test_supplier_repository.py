from api.services.supplier_repository import supplier_repository

print("")
print("========== SUPPLIER TEST ==========")

result = supplier_repository.search(
    page=1,
    page_size=5,
)

print("Total:", result["total"])
print("Page:", result["page"])
print("Page size:", result["page_size"])
print("Total pages:", result["total_pages"])
print("Returned:", len(result["data"]))

print("")
print("========== FIRST SUPPLIER ==========")

if result["data"]:
    print(result["data"][0])

print("")
print("========== STATES ==========")

states = supplier_repository.get_states()
print("State count:", len(states))
print("First states:", states[:10])
