from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

import socket
import time
import errno
import threading

app = Flask(__name__)

# Allow CORS
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*")

drones = [
    # {
    #     "id": 0,
    #     "name": "Drone 0",
    #     "location": (0, 0, 0),
    #     "battery": 90,
    #     "streaming": False,
    #     "status": "on_ground",
    #     "ip": "172.16.0.240"
    # },
    {
        "id": 1,
        "name": "Drone 1",
        "location": (0, 0, 0),
        "battery": 90,
        "streaming": False,
        "status": "on_ground",
        "ip": "172.16.0.103"
    }
]

def api_send(host, message, port=12306, timeout=5, retries=0):
    """Sends a message to a specific host using sockets."""
    ip = ''
    s = None
    try:
        if "." not in host:
            ip = socket.gethostbyname(host)
        else:
            ip = host

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(timeout)

        s.connect((ip, port))
        s.send(message.encode('utf8'))
        response = s.recv(1024)

        return response.decode('utf8')
    
    except socket.error as se:
        if retries > 0:
            time.sleep(0.1)
            return api_send(host, message, port, retries - 1)

        err = se.args[0]
        print(f"SOCKET ERROR for drone {host}: {se}")
        if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
            print('No data available')
    except Exception as e:
        if retries > 0:
            time.sleep(0.1)
            return api_send(host, message, port, retries - 1)
        print(f"Error: {e}")
    finally:
        if s:
            s.close()
    return None

def get_drone_by_id(drone_id):
    return next((drone for drone in drones if drone["id"] == drone_id), None)

def update_battery():
    while True:
        for drone in drones:
            try:
                battery_response = api_send(drone["ip"], "get_battery")
                if battery_response:
                    #If battery_response contains "Error" it means that the drone is not reachable
                    if "Error" in battery_response:
                        print(f"Error actualizando batería del dron {drone['id']}: {battery_response}")
                        continue
                    else:
                        drone["battery"] = int(battery_response)
                    
                    socketio.emit('drone_update', drone)
                    print(f"Actualizada batería del dron {drone['id']} a {drone['battery']}%")
            except Exception as e:
                print(f"Error actualizando batería del dron {drone['id']}: {e}")
        
        time.sleep(30)

# Start battery update thread
def start_battery_update_thread():
    battery_thread = threading.Thread(target=update_battery)
    battery_thread.daemon = True  # Daemon permite que el hilo se detenga cuando se cierre la aplicación
    battery_thread.start()

# Get all drones
@app.route('/drones', methods=['GET'])
def get_drones():
    return jsonify(drones)  # Devuelve la información de todos los drones

# Get drone status
@app.route('/drones/<int:drone_id>/status', methods=['GET'])
def get_drone_status(drone_id):
    if drone_id in drones:
        return jsonify(drones[drone_id])
    else:
        return jsonify({"error": "Drone not found"}), 404

# Takeoff
@app.route('/drones/<int:drone_id>/takeoff', methods=['POST'])
def takeoff_drone(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        if drone["status"] == "on_ground":
            response = api_send(drone["ip"], "takeoff", port=12306, timeout=20)
            if response:
                drone["status"] = "in_air"
                socketio.emit('drone_update', drone)
                return jsonify({"message": f"Drone {drone_id} is taking off. Response: {response}"})
            else:
                return jsonify({"error": "Failed to communicate with drone."}), 500
        else:
            return jsonify({"message": f"Drone {drone_id} is already in the air."}), 400
    else:
        return jsonify({"error": "Drone not found"}), 404

# Land
@app.route('/drones/<int:drone_id>/land', methods=['POST'])
def land_drone(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        if drone["status"] == "in_air":
            response = api_send(drone["ip"], "land", port=12306, timeout=20)
            if response:
                drone["status"] = "on_ground"
                socketio.emit('drone_update', drone)
                return jsonify({"message": f"Drone {drone_id} is landing. Response: {response}"})
            else:
                return jsonify({"error": "Failed to communicate with drone."}), 500
        else:
            return jsonify({"message": f"Drone {drone_id} is already on the ground."}), 400
    else:
        return jsonify({"error": "Drone not found"}), 404

# Go to
@app.route('/drones/<int:drone_id>/goto', methods=['POST'])
def goto_location(drone_id):
    if drone_id in drones:
        data = request.json
        if "location" in data:
            drones[drone_id]["location"] = data["location"]
            return jsonify({"message": f"Drone {drone_id} is going to {data['location']}."})
        else:
            return jsonify({"error": "Location data missing"}), 400
    else:
        return jsonify({"error": "Drone not found"}), 404


# Emergency
@app.route('/drones/<int:drone_id>/emergency', methods=['POST'])
def emergency_drone(drone_id):
    if drone_id in drones:
        drones[drone_id]["status"] = "emergency"
        response = api_send(drone["ip"], "stop", port=12306, timeout=10)
        if response:
            drone["status"] = "on_ground"
            socketio.emit('drone_update', drone)
            return jsonify({"message": f"Drone {drone_id} stopped. Response: {response}"})
        else:
            return jsonify({"error": "Failed to communicate with drone."}), 500
        return jsonify({"message": f"Emergency triggered for drone {drone_id}."})
    else:
        return jsonify({"error": "Drone not found"}), 404

# Stop
@app.route('/drones/<int:drone_id>/stop', methods=['POST'])
def stop_drone(drone_id):
    if drone_id in drones:
        drones[drone_id]["streaming"] = False
        drones[drone_id]["status"] = "on_ground"
        return jsonify({"message": f"Drone {drone_id} has stopped."})
    else:
        return jsonify({"error": "Drone not found"}), 404

# Start streaming
@app.route('/drones/<int:drone_id>/streamon', methods=['POST'])
def start_stream(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        #response = api_send(drone["ip"], "streamon", port=12306)
        response = True
        print(response)
        if response:
            drone["streaming"] = True
            socketio.emit('drone_update', drone)
            return jsonify({"message": f"Drone {drone_id} is streaming."})
    else:
        return jsonify({"error": "Drone not found"}), 404

# Stop streaming
@app.route('/drones/<int:drone_id>/streamoff', methods=['POST'])
def stop_stream(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        #response = api_send(drone["ip"], "streamoff", port=12306)
        response = True
        if response:
            print(response)
            drone["streaming"] = False
            socketio.emit('drone_update', drone)
            return jsonify({"message": f"Drone {drone_id} has stopped streaming."})
    else:
        return jsonify({"error": "Drone not found"}), 404

if __name__ == '__main__':
    #start_battery_update_thread()
    app.run(host='0.0.0.0', port=5000, debug=True)
