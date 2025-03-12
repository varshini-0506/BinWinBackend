from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import pytz
import logging
from datetime import datetime
from db_utils import get_db_connection
from flask_cors import CORS
import time
from opencage.geocoder import OpenCageGeocode
from gradio_client import Client, handle_file

app = Flask(__name__)  
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

HF_SPACE = "BinWin/BinWin" 

def count_bins(image_url):
    """Send an image to the Hugging Face Space and get the bin count."""
    try:
        client = Client(HF_SPACE)
        result = client.predict(
            image=handle_file(image_url),  # Process image URL
            api_name="/predict"  # Use correct API endpoint
        )

        print(f"✅ Bin count received: {result}")
        return result  # This should now be a number

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
    
@app.route('/quiz_scores', methods=['POST'])
def submit_score():
    """Save the quiz score for a user."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')  # User ID from frontend (ensure it's retrieved correctly after login)
        score = data.get('score')

        if not user_id or score is None:
            return jsonify({"error": "User ID and score are required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                INSERT INTO quiz_scores (user_id, score, time)
                VALUES (%s, %s, NOW())
                RETURNING id, user_id, score, time
                """
                cursor.execute(query, (user_id, score))
                quiz_score = cursor.fetchone()
                conn.commit()

        return jsonify({
            "message": "Quiz score submitted successfully",
            "quiz_score": {
                "quiz_id": quiz_score[0],
                "user_id": quiz_score[1],
                "score": quiz_score[2],
                "time": quiz_score[3]
            }
        }), 201

    except Exception as e:
        logger.error(f"Score submission error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

def get_coordinates(location):
    key = "a4f84f6c78c84eae943ae67ef91df333"  # Sign up at https://opencagedata.com/api
    geocoder = OpenCageGeocode(key)
    
    result = geocoder.geocode(location)
    if result:
        return f"{result[0]['geometry']['lat']}, {result[0]['geometry']['lng']}"
    
    return None
    
@app.route('/getprofile', methods=['POST'])
def get_profile():
    """Create or update user profile."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')  
        name = data.get('name')
        bio = data.get('bio')
        location = data.get('location')
        age = str(data.get('age'))  # Ensure age is stored as VARCHAR
        profile_image = data.get('profile_image')
        coordinates = get_coordinates(location) if location else None


        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Check if the profile exists by user_id
                cursor.execute("SELECT id FROM user_profile WHERE user_id = %s", (user_id,))
                existing_profile = cursor.fetchone()

                if existing_profile:
                    # Update existing profile
                    query = """
                        UPDATE user_profile 
                        SET name = %s, bio = %s, location = %s, age = %s, profile_image = %s, coordinates = %s
                        WHERE user_id = %s
                        RETURNING id, user_id, name, bio, location, age, profile_image, coordinates, level, points, visit, streaks, waste_weight
                    """
                    cursor.execute(query, (name, bio, location, age, profile_image, coordinates, user_id))
                else:
                    # Insert new profile
                    query = """
                        INSERT INTO user_profile (user_id, name, bio, location, age, profile_image, coordinates, level, points, visit, streaks, waste_weight)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 0, 0)
                        RETURNING id, user_id, name, bio, location, age, profile_image, coordinates, level, points, visit, streaks, waste_weight
                    """
                    cursor.execute(query, (user_id, name, bio, location, age, profile_image, coordinates))

                profile = cursor.fetchone()
                conn.commit()

                return jsonify({
                    "message": "Profile created or updated successfully",
                    "profile": {
                        "id": profile[0],  # Auto-generated ID
                        "user_id": profile[1],
                        "name": profile[2],
                        "bio": profile[3],
                        "location": profile[4],
                        "age": profile[5],
                        "profile_image": profile[6],
                        "coordinates": profile[7],
                        "level": profile[8],
                        "points": profile[9],
                        "visit": profile[10],
                        "streaks": profile[11],
                        "waste_weight": profile[12]
                    }
                }), 200
    except Exception as e:
        logging.error(f"Profile creation/update error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


@app.route('/displayprofile', methods=['GET'])
def display_profile():
    """Retrieve a user's profile by user_id."""
    try:
        user_id = request.args.get('user_id')  # Get user_id from query params
        
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT id, user_id, name, bio, location, age, profile_image, coordinates, 
                           level, points, visit, streaks, waste_weight 
                    FROM user_profile WHERE user_id = %s
                """
                cursor.execute(query, (user_id,))
                profile = cursor.fetchone()

                if not profile:
                    return jsonify({"error": "Profile not found"}), 404

                return jsonify({
                    "profile": {
                        "id": profile[0],
                        "user_id": profile[1],
                        "name": profile[2],
                        "bio": profile[3],
                        "location": profile[4],
                        "age": profile[5],
                        "profile_image": profile[6],
                        "coordinates": profile[7],
                        "level": profile[8],
                        "points": profile[9],
                        "visit": profile[10],
                        "streaks": profile[11],
                        "waste_weight": profile[12]
                    }
                }), 200
    except Exception as e:
        logging.error(f"Profile retrieval error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/getcompanyprofile', methods=['POST'])
def get_company_profile():
    """Create or update company profile."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        company_name = data.get('company_name')
        location = data.get('location')
        coordinates = data.get('coordinates')
        contact_number = data.get('contact_number')
        profile_image = data.get('profile_image')
        building_images = data.get('building_images')

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Check if the company profile exists
                cursor.execute("SELECT id FROM company_profile WHERE user_id = %s", (user_id,))
                existing_profile = cursor.fetchone()

                if existing_profile:
                    # Update existing profile
                    query = """
                        UPDATE company_profile 
                        SET company_name = %s, location = %s, coordinates = %s, contact_number = %s, 
                            profile_image = %s, building_images = %s
                        WHERE user_id = %s
                        RETURNING id, user_id, company_name, location, coordinates, contact_number, 
                                  profile_image, visit, building_images;
                    """
                    cursor.execute(query, (company_name, location, coordinates, contact_number, 
                                           profile_image, building_images, user_id))
                else:
                    # Insert new company profile
                    query = """
                        INSERT INTO company_profile (user_id, company_name, location, coordinates, contact_number, 
                                                     profile_image, visit, building_images)
                        VALUES (%s, %s, %s, %s, %s, %s, 0, %s)
                        RETURNING id, user_id, company_name, location, coordinates, contact_number, 
                                  profile_image, visit, building_images;
                    """
                    cursor.execute(query, (user_id, company_name, location, coordinates, contact_number, 
                                           profile_image, building_images))

                profile = cursor.fetchone()
                conn.commit()

                return jsonify({
                    "message": "Company profile created or updated successfully",
                    "profile": {
                        "id": profile[0],
                        "user_id": profile[1],
                        "company_name": profile[2],
                        "location": profile[3],
                        "coordinates": profile[4],
                        "contact_number": profile[5],
                        "profile_image": profile[6],
                        "visit": profile[7],
                        "building_images": profile[8]
                    }
                }), 200

    except Exception as e:
        logging.error(f"Company profile error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/displaycompanyprofile', methods=['GET'])
def display_company_profile():
    """Retrieve and display a company profile."""
    try:
        user_id = request.args.get('user_id')  # Get user_id from query params

        if not user_id:
            return jsonify({"error": "User ID is required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT id, user_id, company_name, location, coordinates, contact_number, 
                           profile_image, visit, building_images
                    FROM company_profile
                    WHERE user_id = %s;
                """
                cursor.execute(query, (user_id,))
                profile = cursor.fetchone()

                if not profile:
                    return jsonify({"error": "Company profile not found"}), 404

                return jsonify({
                    "message": "Company profile retrieved successfully",
                    "profile": {
                        "id": profile[0],
                        "user_id": profile[1],
                        "company_name": profile[2],
                        "location": profile[3],
                        "coordinates": profile[4],
                        "contact_number": profile[5],
                        "profile_image": profile[6],
                        "visit": profile[7],
                        "building_images": profile[8]
                    }
                }), 200

    except Exception as e:
        logging.error(f"Error retrieving company profile: {str(e)}")
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
    
@app.route('/leaderboard', methods=['GET'])
def leaderboard():
    """Endpoint to fetch the top 20 users sorted by points."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT user_id, name, profile_image, points, streaks
                    FROM users
                    ORDER BY points DESC
                    LIMIT 20
                """
                cursor.execute(query)
                leaderboard_data = cursor.fetchall()

                # Format response
                leaderboard_list = [
                    {
                        "user_id": row[0],
                        "name": row[1],
                        "profile_pic": row[2] or "https://via.placeholder.com/100",
                        "points": row[3],
                        "streaks": row[4]
                    } for row in leaderboard_data
                ]

                return jsonify({
                    "message": "Leaderboard fetched successfully",
                    "leaderboard": leaderboard_list
                }), 200

    except Exception as e:
        logging.error(f"Leaderboard fetch error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)
