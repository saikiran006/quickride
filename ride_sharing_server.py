import time
import grpc
import uber_pb2_grpc  # Import generated code from proto file
import uber_pb2
from concurrent import futures
import threading
import mysql.connector
from mysql.connector import Error
import sys
import signal

class LoggingInterceptor(grpc.ServerInterceptor):
    def intercept_service(self, continuation, handler_call_details):
        method_name = handler_call_details.method
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        client_role = "Unknown"
        for key, value in handler_call_details.invocation_metadata:
            if key == "role":
                client_role = value

        print(f"[{timestamp}] Client Role: {client_role}, calling method: {method_name}")

        return continuation(handler_call_details)


class RideManagementSystem:
    def __init__(self):
        try:
            self.connection = mysql.connector.connect(
                host='localhost',
                port=3306,
                database='uber',
                user='root',
                password='root'
            )
            if self.connection.is_connected():
                print("Connected to MySQL database")
                self.cursor = self.connection.cursor()
        except Error as e:
            print(f"Error connecting to database: {e}")
            sys.exit(1)

    def __del__(self):
        if self.connection.is_connected():
            self.cursor.close()
            self.connection.close()
            print("Database connection closed.")

    def register_driver(self, name, client_port, server_port):
        query = "INSERT INTO drivers (name, port, server_port, is_available) VALUES (%s, %s, %s, %s)"
        self.cursor.execute(query, (name, client_port, server_port, True))
        self.connection.commit()
        driver_id = self.cursor.lastrowid 
        # print(f"Driver '{name}' registered (Client Port: {client_port}, Server Port: {server_port})")
        return f"Driver '{name}' registered successfully.", driver_id

    def register_rider(self, name, client_port, server_port):
        query = "INSERT INTO riders (name, port, server_port) VALUES (%s, %s, %s)"
        self.cursor.execute(query, (name, client_port, server_port))
        self.connection.commit()
        rider_id = self.cursor.lastrowid
        # print(f"Rider '{name}' registered (Client Port: {client_port}, Server Port: {server_port})")
        return f"Rider '{name}' registered successfully.", rider_id
    
    def get_all_available_drivers(self):
        query = "SELECT driver_id, server_port FROM drivers WHERE is_available = %s"
        self.cursor.execute(query, (True,))
        available_drivers = self.cursor.fetchall()
        return available_drivers

    def insert_ride(self, rider_id, driver_id, pickup, destination, status):
        query = "INSERT INTO rides (rider_id, driver_id, pickup, destination, status, created_at) VALUES (%s, %s, %s, %s, %s, NOW())"
        self.cursor.execute(query, (rider_id, driver_id, pickup, destination, status))
        self.connection.commit()
        ride_id = self.cursor.lastrowid
        # print(f"Ride created with ID: {ride_id} (Rider: {rider_id}, Driver: {driver_id})")
        return ride_id

    def update_driver_status(self,driver_id,status):
        query = "UPDATE drivers SET is_available=%s WHERE driver_id=%s"
        self.cursor.execute(query,(status,driver_id))
        self.connection.commit()
    
    def update_ride_status(self,ride_id,status):
        query="UPDATE rides SET status=%s WHERE ride_id=%s"
        self.cursor.execute(query,(status,ride_id))
        self.connection.commit()
    
    def update_driver_port(self,driver_id,server_port):
        query = "UPDATE drivers SET server_port=%s where driver_id=%s"
        self.cursor.execute(query,(server_port,driver_id))
        self.connection.commit()
    
    def get_last_ride_status(self, rider_id):
        query = """
        SELECT d.name, r.pickup, r.destination, r.status 
        FROM rides r 
        JOIN drivers d ON r.driver_id = d.driver_id 
        WHERE r.rider_id = %s 
        ORDER BY r.created_at DESC 
        LIMIT 1
        """
        self.cursor.execute(query, (rider_id,))
        
        ride = self.cursor.fetchone() 
        
        if ride:
            return uber_pb2.StatusResponse(
                driver_name=ride[0], 
                pickup=ride[1], 
                destination=ride[2],
                status=ride[3], 
                empty=False
            )
        else:
            return uber_pb2.StatusResponse(empty=True)


class RideServiceServicer(uber_pb2_grpc.RideServiceServicer):
    def __init__(self, server_port):
        self.rms = RideManagementSystem()
        self.server_port = server_port
        self.driver_notifications = {}
        self.rider_notifications = {}
        self.ride_status={}

    def get_client_port(self, context):
        """Extract the client's port from context.peer()"""
        peer_info = context.peer()
        client_port = peer_info.split(':')[-1]
        return client_port

    def RegisterDriver(self, request, context):
        client_port = self.get_client_port(context)
        response_message, driver_id = self.rms.register_driver(request.name, client_port, self.server_port)
        return uber_pb2.RegisterResponse(message=response_message, id=driver_id)

    def RegisterRider(self, request, context):
        client_port = self.get_client_port(context)
        response_message, rider_id = self.rms.register_rider(request.name, client_port, self.server_port)
        return uber_pb2.RegisterResponse(message=response_message, id=rider_id)
    
    def RequestRide(self, request, context):
        rider_id = request.rider_id
        pickup = request.pickup
        destination = request.destination
        drivers = self.rms.get_all_available_drivers()
        for driver in drivers:
            driver_id = (int)(driver[0])
            server_port = driver[1]

            notification_message = f"Rider {rider_id} requests a ride from {pickup} to {destination}."
            self.rms.update_driver_status(driver_id,False)
            ride_id = self.rms.insert_ride(rider_id, driver_id, pickup, destination, 'requested')
            self.ride_status[ride_id]="Requesting"
            self.send_driver_notification(ride_id,driver_id,server_port, notification_message)
            time.sleep(10) 
            if(self.ride_status[ride_id]=="Accepted"):
                return uber_pb2.RideResponse(message="Ride Accepted!")
            self.rms.update_driver_status(driver_id,True)
        return uber_pb2.RideResponse(message="Unable to find drivers currently!")

    def AcceptRide(self, request, context):
        ride_id=request.ride_id
        self.ride_status[ride_id]="Accepted"
        self.rms.update_ride_status(ride_id,"Accepted")
        return uber_pb2.AcceptRideResponse(message="Ride Accepted")

    def RejectRide(self,request,context):
        ride_id=request.ride_id
        self.ride_status[ride_id]="Rejected"
        self.rms.update_ride_status(ride_id,"Rejected")
        return uber_pb2.RejectRideResponse(message="Ride Rejected")

    def CompleteRide(self,request,context):
        ride_id=request.ride_id
        driver_id=request.driver_id
        self.ride_status[ride_id]="Completed"
        self.rms.update_ride_status(ride_id,"Completed")
        self.rms.update_driver_status(driver_id,True)
        return uber_pb2.CompleteRideResponse(message="Ride Completed")
    
    def GetRideStatus(self, request, context):
        rider_id = request.rider_id
        return self.rms.get_last_ride_status(rider_id)

    def Exit(self,request,context):
        role=request.role
        registered_id=request.registered_id
        if(role=="driver"):
            self.rms.update_driver_status(registered_id,False)
            return uber_pb2.ExitResponse(message="Driver Exited")
        else:
            return uber_pb2.ExitResponse(message="Rider Exited")

    def DriverNotificationService(self, request, context):
        """Stream driver notifications"""
        driver_id = request.id
        print(f"Driver Id is {driver_id}")
        if driver_id not in self.driver_notifications:
            client_port = self.get_client_port(context)
            self.rms.update_driver_port(driver_id,self.server_port)
            self.driver_notifications[driver_id] = []
        try:
            while True:
                if self.driver_notifications[driver_id]:
                    notification = self.driver_notifications[driver_id].pop(0)
                    yield notification 
                    time.sleep(1)
        except grpc.RpcError:
            print(f"Driver {driver_id} disconnected.")

    def RiderNotificationService(self, request, context):
        """Stream rider notifications"""
        rider_id = request.id
        if rider_id not in self.rider_notifications:
            self.rider_notifications[rider_id] = []
        try:
            while True:
                if self.rider_notifications[rider_id]:
                    notification = self.rider_notifications[rider_id].pop(0)
                    yield uber_pb2.RiderNotificationResponse(notification=notification)
                time.sleep(1)
        except grpc.RpcError:
            print(f"Rider {rider_id} disconnected.")

    def ServerNotificationService(self, request, context):
        driver_id = request.driver_id
        ride_id = request.ride_id
        server_port = request.server_port
        notification = request.notification
        self.send_driver_notification(ride_id, driver_id, server_port, notification)        
        return uber_pb2.ServerNotificationResponse(message="Notification processed successfully")



    def send_driver_notification(self, ride_id, driver_id, server_port, notification):
        """Send notification to the driver."""
        print("debugging",type(driver_id),driver_id, "drivers in current server : ",self.driver_notifications.keys())
        if driver_id in self.driver_notifications:
            notification_response = uber_pb2.DriverNotificationResponse(ride_id=ride_id, notification=notification)
            self.driver_notifications[driver_id].append(notification_response)
            print(f"Notification queued for driver {driver_id}: {notification}")
        else:
            print(f"Driver not connected to the current server {self.server_port}")
            with grpc.insecure_channel(f'localhost:{server_port}') as channel:
                stub = uber_pb2_grpc.RideServiceStub(channel)
                notification_request = uber_pb2.ServerNotificationRequest(
                    driver_id=driver_id,
                    ride_id=ride_id,
                    server_port=server_port,
                    notification=notification
                )
                try:
                    print(f"trying to forwarded to server at port {server_port}")
                    response = stub.ServerNotificationService(notification_request)
                    print(f"Notification forwarded to server at port {server_port}: {response.message}")
                except grpc.RpcError as e:
                    print(f"Error sending notification: {e.details()}")



    def send_rider_notification(self, rider_id, notification):
        if rider_id in self.rider_notifications:
            self.rider_notifications[rider_id].append(notification)
            print(f"Notification queued for rider {rider_id}: {notification}")

def serve(server_port, servers):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10),interceptors=[LoggingInterceptor()])
    ride_service = RideServiceServicer(server_port)
    uber_pb2_grpc.add_RideServiceServicer_to_server(ride_service, server)
    server.add_insecure_port(f'[::]:{server_port}')
    server.start()
    print(f"Server started on port {server_port}")
    servers.append(server)
    server.wait_for_termination()


def signal_handler(servers):
    print("Shutting down servers...")
    for server in servers:
        server.stop(0)
    print("All servers stopped.")
    sys.exit(0)


if __name__ == '__main__':
    ports = [50052,50053,50054] 
    servers = []

    signal.signal(signal.SIGINT, lambda s, f: signal_handler(servers))

    server_threads = []
    for port in ports:
        thread = threading.Thread(target=serve, args=(port, servers))
        thread.start()
        server_threads.append(thread)

    for thread in server_threads:
        thread.join()
