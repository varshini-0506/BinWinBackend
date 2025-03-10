from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import pytz
import logging
from datetime import datetime
from db_utils import get_db_connection
from flask_cors import CORS

app = Flask(__name__)  
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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

@app.route('/getprofile', methods=['POST'])
def get_profile():
    """Create a new profile or update if already exists."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        name = data.get('name')
        bio = data.get('bio')
        location = data.get('location')
        age = data.get('age')
        profile_image = data.get('profile_image')
        coordinates = data.get('coordinates')
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    INSERT INTO user_profile (user_id, name, bio, location, age, profile_image, coordinates, level, points, visit, streaks)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 0)
                    ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    bio = EXCLUDED.bio,
                    location = EXCLUDED.location,
                    age = EXCLUDED.age,
                    profile_image = EXCLUDED.profile_image,
                    coordinates = EXCLUDED.coordinates
                    RETURNING *
                """
                cursor.execute(query, (user_id, name, bio, location, age, profile_image, coordinates))
                profile = cursor.fetchone()
                conn.commit()
                
                return jsonify({
                    "message": "Profile created or updated successfully",
                    "profile": profile
                }), 200
    except Exception as e:
        logging.error(f"Profile creation/update error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/displayprofile/<int:user_id>', methods=['GET'])
def display_profile(user_id):
    """Display profile details without coordinates."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = "SELECT user_id, name, bio, location, age, profile_image, level, points, visit, streaks FROM user_profile WHERE user_id = %s"
                cursor.execute(query, (user_id,))
                profile = cursor.fetchone()
                
                if not profile:
                    return jsonify({"error": "Profile not found"}), 404
                
                return jsonify({
                    "message": "Profile retrieved successfully",
                    "profile": {
                        "user_id": profile[0],
                        "name": profile[1],
                        "bio": profile[2],
                        "location": profile[3],
                        "age": profile[4],
                        "profile_image": profile[5],
                        "level": profile[6],
                        "points": profile[7],
                        "visit": profile[8],
                        "streaks": profile[9]
                    }
                }), 200
    except Exception as e:
        logging.error(f"Profile retrieval error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)