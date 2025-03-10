from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import pytz
import logging
from datetime import datetime
from db_utils import get_db_connection
from flask_cors import CORS
from ultralytics import YOLO
import torchvision.transforms as transforms
from PIL import Image
import requests
from io import BytesIO

app = Flask(__name__)  
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# cloudinary.config(
#     cloud_name="dmpvchis3",
#     api_key="685557167882957",
#     api_secret="ttqAKZzmhHbOnOcRdlVL2sqILSc"
# )

# Load YOLO model
model_path = "yolo_bins.pt"  # Ensure the correct model path
model = YOLO(model_path)

# Define image transformations
transform = transforms.Compose([
    transforms.Resize((640, 640)),  # Resize for YOLO
    transforms.ToTensor(),  # Convert to tensor
])

def count_bins(image_url):
    """Download and process the image to count the number of bins."""
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()  

        image = Image.open(BytesIO(response.content)).convert("RGB")  # Convert to RGB

        results = list(model(image, stream=True))  

        if not results:  
            print("❌ No objects detected.")
            return 0

        num_bins = len(results[0].boxes)  
        print(f"🔢 Number of bins detected: {num_bins}")

        return num_bins

    except requests.exceptions.RequestException as req_err:
        print(f"❌ HTTP request error: {str(req_err)}")
        return None

    except Exception as e:
        print(f"❌ Error processing image: {str(e)}")
        return None

@app.route('/signup', methods=['POST'])
def signup():
    """Endpoint for user signup."""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirmPassword')
        role = data.get('role')

        if not email or not password or not confirm_password or not role:
            return jsonify({"error": "All fields are required"}), 400

        if password != confirm_password:
            return jsonify({"error": "Password and confirm password do not match"}), 400

        if len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters long"}), 400

        hashed_password = generate_password_hash(password)

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                current_time = datetime.now(pytz.utc)
                query = """
                    INSERT INTO users (email, password, role, time)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, email, role, time
                """
                cursor.execute(query, (email, hashed_password, role, current_time))
                user = cursor.fetchone()
                conn.commit()

                return jsonify({
                    "message": "Signup successful",
                    "user": {
                        "user_id": user[0],
                        "email": user[1],
                        "role": user[2],
                        "time": user[3]
                    }
                }), 201
            
    except Exception as e:
        logging.error(f"Signup error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
@app.route('/login', methods=['POST'])
def login():
    """Endpoint for user login."""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        role = data.get('role')

        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = "SELECT id, email, password, role, time FROM users WHERE email = %s"
                cursor.execute(query, (email,))
                user = cursor.fetchone()

                if user and check_password_hash(user[2], password):
                    # Update last login time
                    update_query = "UPDATE users SET time = %s WHERE email = %s"
                    current_time = datetime.now(pytz.utc)
                    cursor.execute(update_query, (current_time, email))
                    conn.commit()

                    return jsonify({
                        "message": "Login successful",
                        "user": {
                            "user_id": user[0],
                            "email": user[1],
                            "type": user[3],
                            "last_login": user[4]
                        }
                    }), 200
                else:
                    return jsonify({"error": "Invalid email or password"}), 401
    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
@app.route('/wasteUpload', methods=['POST'])
def process_waste_image():
    """Endpoint to process waste images and store in Neon DB."""
    try:
        data = request.get_json()
        level = data.get('level')
        front_view = data.get('front_view')  # URL of front view image
        top_view = data.get('top_view')  # URL of top view image
        user_id = data.get('user_id')

        if not level or not front_view or not top_view or not user_id:
            return jsonify({"error": "All fields are required"}), 400

        # Count bins using YOLO on the front_view image
        bin_count = count_bins(front_view)

        if bin_count is None:
            return jsonify({"error": "Error processing image"}), 500

        if bin_count != 3:
            return jsonify({"message": f"Image does not meet the required criteria. Bins detected: {bin_count}","data":bin_count}), 400

        combined_images = f"{front_view},{top_view}"

        # Store data in Neon DB
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                current_time = datetime.now(pytz.utc)
                query = """
                    INSERT INTO wasteimages (user_id, level, image, time)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """
                cursor.execute(query, (user_id, level, combined_images , current_time))
                image_id = cursor.fetchone()[0]
                conn.commit()

                return jsonify({
                    "message": "3 bin detected and image uploaded successfully",
                    "data":3,
                    "image_id": image_id
                }), 201

    except Exception as e:
        logging.error(f"Process waste image error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)