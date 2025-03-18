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

HF_BIN_DETECTION_SPACE = "BinWin/BinWin"
HF_WASTE_CLASSIFICATION_SPACE = "BinWin/Wasteclassification"

def count_bins(image_url):
    """Send an image to the Hugging Face Space and get the bin count."""
    try:
        client = Client(HF_BIN_DETECTION_SPACE)
        result = client.predict(
            handle_file(image_url),  # Process image URL
            api_name="/predict"
        )

        print(f"✅ Bin count received: {result}")
        return int(result)  # Ensure we return the bin count

    except Exception as e:
        print(f"❌ Error processing image: {str(e)}")
        return None

def classify_waste(image_url):
    """Send an image to the Hugging Face Space for waste classification."""
    try:
        client = Client(HF_WASTE_CLASSIFICATION_SPACE)
        result = client.predict(
            handle_file(image_url),  # Process image URL
            api_name="/predict"
        )

        print(f"✅ Classification result: {result}")
        return result

    except Exception as e:
        print(f"❌ Error classifying waste: {str(e)}")
        return "error"
    
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
    """Update total points in user_profile when a user completes a quiz."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')  # Ensure it's retrieved correctly after login
        score = data.get('score')

        if not user_id or score is None:
            return jsonify({"error": "User ID and score are required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Update the points in user_profile by adding the new score
                update_query = """
                UPDATE user_profile 
                SET points = COALESCE(points, 0) + %s 
                WHERE user_id = %s
                RETURNING user_id, points
                """
                cursor.execute(update_query, (score, user_id))
                updated_user = cursor.fetchone()
                conn.commit()

        return jsonify({
            "message": "Quiz score updated successfully",
            "user_profile": {
                "user_id": updated_user[0],
                "total_points": updated_user[1]
            }
        }), 200

    except Exception as e:
        logger.error(f"Score update error: {str(e)}")
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
        contact_number = data.get('contact_number')
        profile_image = data.get('profile_image')
        building_images = data.get('building_images')
        coordinates = get_coordinates(location) if location else None

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
        top_views = data.get('top_views')    # List of top view images
        user_id = data.get('user_id')

        if not all([level, front_view, top_views, user_id]):
            return jsonify({"error": "All fields are required"}), 400

        if not isinstance(top_views, list) or len(top_views) > 3:
            return jsonify({"error": "top_views must be a list of max 3 URLs"}), 400

        # Step 1: Count bins using YOLO on the front_view image
        bin_count = count_bins(front_view)

        if bin_count is None:
            return jsonify({"error": "Error processing front view image"}), 500

        # Step 2: Validate the number of bins
        if bin_count != len(top_views):
            return jsonify({
                "message": f"Mismatch: {bin_count} bins detected but {len(top_views)} top views provided.",
                "detected_bins": bin_count
            }), 400

         # Step 3: Classify waste in each bin
        classification_results = [classify_waste(tv) for tv in top_views]

        # Check if any classification contains more than one unique class (not properly sorted)
        improperly_sorted = any(len(set(result)) > 1 for result in classification_results)

        # Check if all classifications are unique
        unique_classes = len(set(tuple(sorted(set(result))) for result in classification_results)) == len(classification_results)

        if improperly_sorted:
            return jsonify({
                "message": "Waste is not properly sorted. Some bins contain multiple distinct classes.",
                "classification_results": classification_results
            }), 400

        if not unique_classes:
            return jsonify({
                "message": "Waste is not properly sorted. Duplicate waste classes found across bins.",
                "classification_results": classification_results
            }), 400

        combined_images = f"{front_view},{','.join(top_views)}"

        # Step 4: Store data in Neon DB
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                current_time = datetime.now(pytz.utc)
                query = """
                    INSERT INTO wasteimages (user_id, level, image, time)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """
                cursor.execute(query, (user_id, level, combined_images, current_time))
                image_id = cursor.fetchone()[0]
                conn.commit()

                return jsonify({
                    "message": "Bins detected, images uploaded, and classification done successfully",
                    "detected_bins": bin_count,
                    "classification_results": classification_results,
                    "image_id": image_id
                }), 201

    except Exception as e:
        logging.error(f"Process waste image error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
@app.route('/leaderboard', methods=['GET'])
def leaderboard():
    """Endpoint to fetch the top 20 users sorted by points."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT user_id, name, profile_image, points, streaks
                    FROM user_profile
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
    
@app.route('/getalluserprofile', methods=['GET'])
def get_all_user_profiles():
    """Fetch all users' profile coordinates, names, and bios."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = "SELECT user_id, name, bio, coordinates FROM user_profile WHERE coordinates IS NOT NULL"
                cursor.execute(query)
                profiles = cursor.fetchall()

        # Format response
        user_profiles = []
        for profile in profiles:
            user_id, name, bio, coordinates = profile  # Extract values from the tuple
            if coordinates:
                lat, lon = map(float, coordinates.strip("()").split(","))  # Convert to float
                user_profiles.append({
                    "user_id": user_id,
                    "name": name,
                    "bio": bio,
                    "latitude": lat,
                    "longitude": lon
                })

        return jsonify({"locations": user_profiles}), 200
    except Exception as e:
        logging.error(f"Error fetching user profiles: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/displaycompany', methods=['GET'])
def display_company_coordinates():
    """Fetch coordinates for a specific company by user_id."""
    try:
        user_id = request.args.get('user_id')  # Get user_id from query params

        if not user_id:
            return jsonify({"error": "User ID is required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = "SELECT company_name, coordinates FROM company_profile WHERE user_id = %s AND coordinates IS NOT NULL"
                cursor.execute(query, (user_id,))
                company = cursor.fetchone()

                if not company:
                    return jsonify({"error": "Company profile not found or coordinates not available"}), 404

                coordinates = company[1]  # Assuming stored as (latitude, longitude)
                if coordinates:
                    lat, lon = map(float, coordinates.strip("()").split(","))  # Convert to float

                    return jsonify({
                        "user_id": user_id,
                        "company_name": company[0],
                        "latitude": lat,
                        "longitude": lon
                    }), 200

        return jsonify({"error": "Company profile not found"}), 404

    except Exception as e:
        logging.error(f"Error fetching company coordinates: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
@app.route('/companySchedule', methods=['POST'])
def create_schedule():
    """Insert scheduling data into the scheduling table."""
    try:
        data = request.get_json()
        company_id = data.get('company_id')
        user_id = data.get('user_id')
        date = data.get('date')
        time = data.get('time')

        # Validate input
        if not all([company_id, user_id, date, time]):
            return jsonify({"error": "Missing required fields"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                INSERT INTO scheduling (company_id, user_id, date, time)
                VALUES (%s, %s, %s, %s)
                """
                cursor.execute(query, (company_id, user_id, date, time))
                conn.commit()

        return jsonify({"message": "Schedule created successfully"}), 201

    except Exception as e:
        logging.error(f"Error inserting schedule: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/displayuserSchedule', methods=['GET'])
def get_user_schedule():
    """Fetch schedule details and corresponding company profiles for a given user_id."""
    try:
        user_id = request.args.get('user_id')

        # Validate input
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                SELECT s.id , s.company_id, s.date, s.time, c.company_name, c.contact_number, c.profile_image, c.price, s.status
                FROM scheduling s
                JOIN company_profile c ON s.company_id = c.user_id
                WHERE s.user_id = %s
                """
                cursor.execute(query, (user_id,))
                results = cursor.fetchall()

        # Format the output
        schedules = [
            {
                "schedule_id": row[0],
                "company_id": row[1],
                "date": row[2].strftime('%Y-%m-%d'),
                "time": str(row[3]),
                "company_name": row[4],
                "contact_number": row[5],
                "profile_image": row[6],
                "price": row[7],
                "status": row[8]
            }
            for row in results
        ]

        return jsonify({"schedules": schedules}), 200

    except Exception as e:
        logging.error(f"Error fetching schedule: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
@app.route('/displayCompanySchedule', methods=['GET'])
def get_company_schedule():
    """Fetch schedule details and corresponding user profiles for a given company_id."""
    try:
        user_id = request.args.get('user_id')

        # Validate input
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Fetch schedule and user profile details
            query = """
                SELECT s.user_id, s.reason, s.status, s.date, s.time, u.name, u.location, u.profile_image , s.id
                FROM scheduling s
                JOIN user_profile u ON s.user_id = u.user_id
                WHERE s.company_id = %s
            """
            cursor.execute(query, (user_id,))
            results = cursor.fetchall()

        # Format the output
        schedules = [
            {
                "user_id": row[0],
                "reason": row[1],
                "status": row[2],
                "date": row[3],
                "time": row[4].strftime('%H:%M:%S') if row[4] else None,
                "name": row[5],
                "location": row[6],
                "profile_image": row[7],
                "schedule_id": row[8]
            }
            for row in results
        ]

        if not schedules:
            return jsonify({"message": "No records found"}), 404

        return jsonify({"schedules": schedules}), 200

    except Exception as e:
        logging.error(f"Error fetching schedule: {str(e)}")
@app.route('/acceptSchedule', methods=['POST'])
def accept_schedule():
    """Accept a schedule, update visit counts, and use correct DB column name."""
    try:
        data = request.get_json()
        scheduling_id = data.get('id')  # Match DB column name
        company_id = data.get('company_id')
        user_id = data.get('user_id')

        # Validate input
        if not all([scheduling_id, company_id, user_id]):
            return jsonify({"error": "Missing id, company_id, or user_id"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Update scheduling table to set status as accepted
                cursor.execute("""
                    UPDATE scheduling 
                    SET status = 'accepted' 
                    WHERE id = %s AND company_id = %s AND user_id = %s
                """, (scheduling_id, company_id, user_id))

                # Check if any row was updated
                if cursor.rowcount == 0:
                    return jsonify({"error": "No matching schedule found"}), 404

                # Increment visit count in user_profile
                cursor.execute("""
                    UPDATE user_profile 
                    SET visit = visit + 1 
                    WHERE user_id = %s
                """, (user_id,))

                # Increment visit count in company_profile
                cursor.execute("""
                    UPDATE company_profile 
                    SET visit = visit + 1 
                    WHERE user_id = %s
                """, (company_id,))

                conn.commit()

        return jsonify({"message": "Schedule accepted successfully"}), 200

    except Exception as e:
        logging.error(f"Error accepting schedule: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/rejectSchedule', methods=['POST'])
def reject_schedule():
    """Reject a schedule, update the reason, and update the date."""
    try:
        data = request.get_json()
        scheduling_id = data.get('id')  # Match DB column name
        company_id = data.get('company_id')
        user_id = data.get('user_id')
        reason = data.get('reason')
        new_date = data.get('date')  # Updated date

        # Validate input
        if not all([scheduling_id, company_id, user_id, reason, new_date]):
            return jsonify({"error": "Missing required fields"}), 400

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Update scheduling table to set status as rejected, store reason, and update date
                cursor.execute("""
                    UPDATE scheduling 
                    SET status = 'rejected', reason = %s, date = %s
                    WHERE id = %s AND company_id = %s AND user_id = %s
                """, (reason, new_date, scheduling_id, company_id, user_id))

                # Check if any row was updated
                if cursor.rowcount == 0:
                    return jsonify({"error": "No matching schedule found"}), 404

                conn.commit()

        return jsonify({"message": "Schedule rejected successfully"}), 200

    except Exception as e:
        logging.error(f"Error rejecting schedule: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


# Run the Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
