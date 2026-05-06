"""
Smart Watering & Automated Fertilization - API Routes
Component 3
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/sensor-data")
async def get_sensor_data():
    """
    Get current environmental sensor readings (temp, humidity, light, moisture).
    """
    # TODO: Fetch from IoT sensors / Firebase
    return {
        "status": "success",
        "message": "Sensor data endpoint - under development",
    }


@router.post("/schedule")
async def create_watering_schedule():
    """
    Create an automated watering/fertilization schedule based on ML predictions.
    """
    # TODO: Implement ML-based scheduling
    return {
        "status": "success",
        "message": "Watering schedule endpoint - under development",
    }
