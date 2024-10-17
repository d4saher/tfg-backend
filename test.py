import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Battery, Video, VideoOff, Plane, PlaneLanding, AlertTriangle, MapPin, Wifi, WifiOff } from "lucide-react";
import DroneStream from "@/components/drone-stream";

import { io } from "socket.io-client";

// Types
type Drone = {
  id: string;
  name: string;
  batteryLevel: number;
  isStreaming: boolean;
  status: string;
  position: { x: number; y: number; z: number };
  ip: string;
};

const api_address = 'http://172.16.0.249:5000';

const socket = io(api_address);

export default function DroneFleetControlComponent() {
  const [drones, setDrones] = useState<Drone[]>([]);
  const [coordinates, setCoordinates] = useState({ x: 0, y: 0, z: 0 });
  const [language, setLanguage] = useState<"en" | "es" | "ca" | "eu">("en");

  // Obtener la información inicial de los drones al cargar la página
  useEffect(() => {
    const fetchInitialDrones = async () => {
      try {
        const response = await fetch(`${api_address}/drones`);
        if (response.ok) {
          const data = await response.json();
          setDrones(data);  // Establece el estado de los drones con la información del backend
        } else {
          console.error('Error al obtener la información de los drones:', await response.text());
        }
      } catch (error) {
        console.error('Error al obtener la información inicial de los drones:', error);
      }
    };

    fetchInitialDrones(); // Llamar a la función para obtener la información inicial de los drones

    // Configurar el socket para recibir actualizaciones en tiempo real
    socket.on('drone_update', (updatedDrone) => {
      console.log("Drone actualizado recibido:", updatedDrone);
      setDrones((prevDrones) =>
        prevDrones.map((drone) =>
          drone.id === updatedDrone?.id?.toString() ? { ...drone, ...updatedDrone } : drone
        )
      );
    });

    return () => {
      socket.off('drone_update');
    };
  }, []);

  // Lógica para enviar comandos al backend
  const sendDroneAction = useCallback(async (droneId: string, action: string) => {
    try {
      let endpoint = `${api_address}/drones/${droneId}`;
      const method = 'POST';
      const body = null;

      switch (action) {
        case 'takeoffLand': {
          const drone = drones.find((drone) => drone.id === droneId);
          if (drone) {
            if (drone.status === "in_air") {
              endpoint += '/land';
            } else if (drone.status === "on_ground") {
              endpoint += '/takeoff';
            }
          }
          break;
        }
        case 'emergency': {
          endpoint += '/emergency';
          break;
        }
        case 'toggleStream': {
          const drone = drones.find((drone) => drone.id === droneId);
          if (drone?.isStreaming) {
            endpoint += '/stop';
          } else {
            endpoint += '/start';
          }
          break;
        }
        default: {
          console.error('Acción desconocida:', action);
          return;
        }
      }

      const response = await fetch(endpoint, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: body ? JSON.stringify(body) : null,
      });

      if (!response.ok) {
        console.error('Error en la solicitud:', await response.text());
      } else {
        console.log(`Acción ${action} enviada correctamente para el dron ${droneId}`);
      }
    } catch (error) {
      console.error('Error enviando la acción:', error);
    }
  }, [drones]);

  const handleDroneAction = (droneId: string, action: string) => {
    sendDroneAction(droneId, action);
  };

  const handleGoTo = (droneId: string) => {
    const endpoint = `${api_address}/drones/${droneId}/goto`;
    const body = {
      location: [coordinates.x, coordinates.y, coordinates.z],
    };

    fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
      .then((response) => response.json())
      .then((data) => {
        console.log(`Dron ${droneId} enviado a ${coordinates.x}, ${coordinates.y}, ${coordinates.z}`);
      })
      .catch((error) => {
        console.error('Error enviando las coordenadas:', error);
      });
  };

  return (
    <Card className="w-full max-w-7xl mx-auto">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Drone Fleet Control</CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[calc(100vh-12rem)] pr-4">
          <div className="grid gap-4">
            {drones.map((drone) => (
              <Card key={drone.id} className="p-4">
                <div className="flex flex-col gap-4">
                  <div className="flex-grow">
                    <div className="flex justify-between items-center mb-4">
                      <h3 className="text-lg font-semibold">{drone.name}</h3>
                      <div className="flex items-center gap-2">
                        <Battery className="h-4 w-4" />
                        <span>{drone.batteryLevel}% Battery</span>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                      <div className="flex items-center gap-2">
                        <MapPin className="h-4 w-4" />
                        <span>
                          {drone.position.x}, {drone.position.y}, {drone.position.z}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        {drone.isStreaming ? (
                          <Video className="h-4 w-4 text-green-500" />
                        ) : (
                          <VideoOff className="h-4 w-4 text-red-500" />
                        )}
                        <span>{drone.isStreaming ? "Streaming" : "Not streaming"}</span>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      <Button size="sm" onClick={() => handleDroneAction(drone.id, "takeoffLand")}>
                        {drone.status === "in_air" ? (
                          <>
                            <PlaneLanding className="mr-2 h-4 w-4" /> Land
                          </>
                        ) : (
                          <>
                            <Plane className="mr-2 h-4 w-4" /> Take Off
                          </>
                        )}
                      </Button>
                      <Button size="sm" onClick={() => handleGoTo(drone.id)}>
                        Go To
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => handleDroneAction(drone.id, "emergency")}>
                        <AlertTriangle className="mr-2 h-4 w-4" /> Emergency
                      </Button>
                      <Button size="sm" onClick={() => handleDroneAction(drone.id, "toggleStream")}>
                        {drone.isStreaming ? (
                          <>
                            <VideoOff className="mr-2 h-4 w-4" /> Stop Stream
                          </>
                        ) : (
                          <>
                            <Video className="mr-2 h-4 w-4" /> Start Stream
                          </>
                        )}
                      </Button>
                    </div
