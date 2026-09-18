ENTERPRISES = [
    {
        "id": "UDYAM-AP-001",
        "state": "Andhra Pradesh",
        "district": "Konaseema",
        "pincode": "533201",
        "registrationDate": "2023-04-18",
        "enterpriseName": "Demo Engineering Works",
        "communicationAddress": "Amalapuram, Andhra Pradesh",
        "activities": "Manufacturing",
    },
    {
        "id": "UDYAM-TS-001",
        "state": "Telangana",
        "district": "Hyderabad",
        "pincode": "500072",
        "registrationDate": "2022-08-11",
        "enterpriseName": "Demo Technologies Private Limited",
        "communicationAddress": "KPHB, Hyderabad, Telangana",
        "activities": "Information Technology",
    },
    {
        "id": "UDYAM-KA-001",
        "state": "Karnataka",
        "district": "Bengaluru Urban",
        "pincode": "560001",
        "registrationDate": "2024-01-09",
        "enterpriseName": "Demo Digital Solutions",
        "communicationAddress": "Bengaluru, Karnataka",
        "activities": "IT Services",
    },
    {
        "id": "UDYAM-MH-001",
        "state": "Maharashtra",
        "district": "Mumbai",
        "pincode": "400001",
        "registrationDate": "2023-11-22",
        "enterpriseName": "Demo Manufacturing Industries",
        "communicationAddress": "Mumbai, Maharashtra",
        "activities": "Manufacturing",
    },
    {
        "id": "UDYAM-TN-001",
        "state": "Tamil Nadu",
        "district": "Chennai",
        "pincode": "600001",
        "registrationDate": "2024-03-14",
        "enterpriseName": "Demo Industrial Products",
        "communicationAddress": "Chennai, Tamil Nadu",
        "activities": "Manufacturing",
    },
]


def get_all_enterprises():
    return ENTERPRISES


def get_enterprise_by_id(enterprise_id):
    for enterprise in ENTERPRISES:
        if enterprise["id"] == enterprise_id:
            return enterprise

    return None
