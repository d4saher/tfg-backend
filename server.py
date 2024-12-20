from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO
from PIL import Image

import socket
import time
import errno
import threading
import os
import cv2 as cv
import numpy as np

app = Flask(__name__)

# Allow CORS
CORS(app)

CORS(app, resources={
    r"/*": {
        "origins": "http://172.16.0.249:5173",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    }
})

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
        "ip": "172.16.0.241"
    },
    {
        "id": 2,
        "name": "Drone 2",
        "location": (0, 0, 0),
        "battery": 90,
        "streaming": False,
        "status": "on_ground",
        "ip": "172.16.0.105"
    },
    {
        "id": 3,
        "name": "Drone 3",
        "location": (0, 0, 0),
        "battery": 90,
        "streaming": False,
        "status": "on_ground",
        "ip": "172.16.0.106"
    }
]

# Map configuration
MAP_PATH = 'testbed_maps/map.jpg' 
CAMERA_CALIBRATION_PATH = 'cam_parameters.npz'
MARKER_DISTANCE_MM = 300 

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

def load_calibration(calibration_path):
    """Carga los parámetros de calibración de la cámara"""
    try:
        with np.load(calibration_path) as X:
            camera_matrix, dist_coeffs = [X[i] for i in ('camera_matrix', 'dist_coeffs')]
            return camera_matrix, dist_coeffs
    except Exception as e:
        print(f"Error cargando archivo de calibración: {e}")
        return None, None

def get_map_scale():
    """Calcula la escala del mapa basándose en los marcadores Aruco y los parámetros de la cámara"""
    try:
        # Cargar parámetros de la cámara
        calibration_file = 'tello_camera_calibration/cam_parameters.npz'
        camera_matrix, dist_coeffs = load_calibration(CAMERA_CALIBRATION_PATH)
        
        if camera_matrix is None or dist_coeffs is None:
            raise ValueError("No se pudieron cargar los parámetros de calibración")

        # Cargar la imagen
        frame = cv.imread(MAP_PATH)
        if frame is None:
            raise ValueError(f"No se pudo cargar la imagen del mapa: {MAP_PATH}")
        
        # Detectar marcadores Aruco usando la nueva API
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        aruco_dict = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_6X6_250)
        aruco_params = cv.aruco.DetectorParameters()
        detector = cv.aruco.ArucoDetector(aruco_dict, aruco_params)
        corners, ids, _ = detector.detectMarkers(gray)
        
        if ids is None or 0 not in ids:
            raise ValueError("No se encontró el marcador de referencia (ID 0)")
        
        # Estimar poses para cada marcador
        marker_size = 9  # Tamaño del marcador en cm
        rvecs = []
        tvecs = []
        
        # Definir los puntos 3D del marcador
        object_points = np.array([
            [-marker_size/2, marker_size/2, 0],
            [marker_size/2, marker_size/2, 0],
            [marker_size/2, -marker_size/2, 0],
            [-marker_size/2, -marker_size/2, 0]
        ], dtype=np.float32)

        for corner in corners:
            success, rvec, tvec = cv.solvePnP(
                objectPoints=object_points,
                imagePoints=corner[0],
                cameraMatrix=camera_matrix,
                distCoeffs=dist_coeffs
            )
            if success:
                rvecs.append(rvec)
                tvecs.append(tvec)

       # Encontrar el marcador 0 (referencia)
        marker_0_idx = np.where(ids == 0)[0][0]
        pos_0 = tvecs[marker_0_idx].flatten()
        rvec_0 = rvecs[marker_0_idx]
        marker_0_corners = corners[marker_0_idx][0]
        marker_0_center = np.mean(marker_0_corners, axis=0)
        
        # Convertir vector de rotación a matriz
        R_0, _ = cv.Rodrigues(rvec_0)
        R_0_inv = R_0.T
        
        # Inicializar variables para los marcadores más alejados
        max_x_distance_mm = 0
        max_y_distance_mm = 0
        max_x_distance_px = 0
        max_y_distance_px = 0
        x_marker_id = None
        y_marker_id = None
        
        # Buscar los marcadores más alejados en X e Y
        for i, marker_id in enumerate(ids):
            if marker_id == 0:
                continue
            
            # Calcular posición relativa en milímetros
            pos_cam = tvecs[i].flatten()
            rel_pos = pos_cam - pos_0
            transformed_pos = np.dot(R_0_inv, rel_pos)
            transformed_pos_mm = transformed_pos * 10  # convertir a mm
            
            # Calcular posición relativa en píxeles
            marker_center = np.mean(corners[i][0], axis=0)
            dx_px = abs(marker_center[0] - marker_0_center[0])
            dy_px = abs(marker_center[1] - marker_0_center[1])
            dx_mm = abs(transformed_pos_mm[0])
            dy_mm = abs(transformed_pos_mm[1])
            
            if dx_mm > max_x_distance_mm:
                max_x_distance_mm = dx_mm
                max_x_distance_px = dx_px
                x_marker_id = marker_id[0]
                
            if dy_mm > max_y_distance_mm:
                max_y_distance_mm = dy_mm
                max_y_distance_px = dy_px
                y_marker_id = marker_id[0]
        
        # Obtener dimensiones de la imagen
        height_px, width_px = frame.shape[:2]
        
        # Calcular escalas (píxeles por milímetro) usando las distancias reales
        scale_x = max_x_distance_px / max_x_distance_mm if max_x_distance_mm > 0 else 1
        scale_y = max_y_distance_px / max_y_distance_mm if max_y_distance_mm > 0 else 1

        print(f"Distancia máxima en X: {max_x_distance_mm:.2f}mm ({max_x_distance_px:.2f}px) con marcador {x_marker_id}")
        print(f"Distancia máxima en Y: {max_y_distance_mm:.2f}mm ({max_y_distance_px:.2f}px) con marcador {y_marker_id}")
        print(f"Escala X: {scale_x:.2f} px/mm")
        print(f"Escala Y: {scale_y:.2f} px/mm")
        
        return {
            "dimensions": {
                "width_px": width_px,
                "height_px": height_px,
                "width_mm": max_x_distance_mm,
                "height_mm": max_y_distance_mm
            },
            "scale": {
                "x": float(scale_x),  # px/mm
                "y": float(scale_y)    # px/mm
            },
            "reference_markers": {
                "origin": 0,
                "max_x": int(x_marker_id) if x_marker_id is not None else None,
                "max_y": int(y_marker_id) if y_marker_id is not None else None,
                "origin_position": {
                    "x": float(marker_0_center[0]),
                    "y": float(marker_0_center[1])
                }
            },
            "distances": {
                "max_x": float(max_x_distance_mm),  # mm
                "max_y": float(max_y_distance_mm),   # mm
                "max_x_px": float(max_x_distance_px),  # px
                "max_y_px": float(max_y_distance_px)   # px
            }
        }
        
    except Exception as e:
        print(f"Error calculando la escala del mapa: {e}")
        import traceback
        traceback.print_exc()
        return None

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

@app.route('/drones/<int:drone_id>/go_to', methods=['POST'])
def goto_location(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        data = request.json
        if drone["status"] == "in_air":
            if "location" in data:
                response = api_send(drone["ip"], f"go_to:{data['location'][0]}, {data['location'][1]}, {data['location'][2]}", port=12306, timeout=20)
                if response:
                    return jsonify({"message": f"Drone {drone_id} is going to {data['location']}."})
                else:
                    return jsonify({"error": "Failed to send command to drone."}), 500
            else:
                return jsonify({"error": "Location data missing"}), 400
        else:
            return jsonify({"error": f"Drone {drone_id} is not in the air."}), 400
    else:
        return jsonify({"error": "Drone not found"}), 404

# Patrol
@app.route('/drones/<int:drone_id>/patrol', methods=['POST'])
def patrol(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        response = api_send(drone["ip"], "patrol", port=12306, timeout=10)
        if response:
            drone["status"] = "on_air"
            return jsonify({"message": "Patrol started successfully"}), 200
        else:
            return jsonify({"error": "Failed to communicate with drone."}), 500    
    else:
        return jsonify({"error": "Drone not found"}), 404

# Emergency
@app.route('/drones/<int:drone_id>/emergency', methods=['POST'])
def emergency_drone(drone_id):
    drone = get_drone_by_id(drone_id)
    if drone:
        drone["status"] = "emergency"
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

# Serve map image
@app.route('/map', methods=['GET'])
def get_map():
    if os.path.exists(MAP_PATH):
        return send_file(MAP_PATH, mimetype='image/jpeg')
    else:
        return jsonify({"error": "Map file not found"}), 404

# Obtener información del mapa (dimensiones y escala)
@app.route('/map/info', methods=['GET'])
def get_map_info():
    try:
        if not os.path.exists(MAP_PATH):
            return jsonify({"error": "Map file not found"}), 404
            
        scale_info = get_map_scale()
        if scale_info is None:
            return jsonify({"error": "Error calculating map scale"}), 500
            
        return jsonify(scale_info)
        
    except Exception as e:
        return jsonify({"error": f"Error processing map info: {str(e)}"}), 500

if __name__ == '__main__':
    #start_battery_update_thread()
    app.run(host='0.0.0.0', port=5000, debug=True)
