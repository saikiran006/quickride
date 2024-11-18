import grpc
import sys
import threading
import time
import random
import uber_pb2_grpc
import uber_pb2

class RideClient:
    def __init__(self):
        self.registered_id = None
        self.role = None
        self.exit_event = threading.Event()
        self.input_lock = threading.Lock()
        self.ride_request_id = 0
        self.accepted = False
        self.timer_event = threading.Event()
        self.metadata = []
        self.servers = ['localhost:50052','localhost:50053','localhost:50054']
        self.current_server_index = 0

    def get_stub(self):
        server = self.servers[self.current_server_index]
        self.current_server_index = (self.current_server_index + 1) % len(self.servers)
        channel = grpc.insecure_channel(server)
        return uber_pb2_grpc.RideServiceStub(channel)

    def get_stub(self):
        int server_ind=(len(self.servers)+self.registered_id)

    def register_driver(self, name):
        stub = self.get_stub() 
        self.metadata = [('role', 'driver')]
        response = stub.RegisterDriver(uber_pb2.RegisterDriverRequest(name=name), metadata=self.metadata)
        self.registered_id = response.id
        print("Driver Registration Response:", response.message)
        print("Registered Driver ID:", self.registered_id)

    def register_rider(self, name):
        stub = self.get_stub()
        self.metadata = [('role', 'rider')]
        response = stub.RegisterRider(uber_pb2.RegisterRiderRequest(name=name), metadata=self.metadata)
        self.registered_id = response.id
        print("Rider Registration Response:", response.message)
        print("Registered Rider ID:", self.registered_id)

    def listen_for_driver_notifications(self):
        stub = self.get_stub()
        for notification in stub.DriverNotificationService(uber_pb2.NotificationRequest(id=self.registered_id), metadata=self.metadata):
            print("Ride Notification received")
            print("Message:", notification.notification)
            print("Ride ID:", notification.ride_id)
            self.ride_request_id = notification.ride_id
            self.start_timer(stub, 10, notification.ride_id)
            print("2. Accept")
            print("3. Reject")

    def start_timer(self, stub, seconds, ride_id):
        self.timer_event.clear()
        timer_thread = threading.Thread(target=self.countdown_timer, args=(stub, seconds, ride_id))
        timer_thread.start()

    def countdown_timer(self, stub, seconds, ride_id):
        for remaining in range(seconds, 0, -1):
            if self.timer_event.is_set():
                print("\nTimer stopped.\n")
                return
            print(f"Time left: {remaining} seconds")
            time.sleep(1)

        print("\nTime's up!")
        if not self.accepted:
            self.reject_ride(stub, self.ride_request_id)
        else:
            self.accepted = False

    def accept_ride(self, ride_id):
        stub = self.get_stub()
        self.accepted = True
        print("Accepting the current ride....")
        self.timer_event.set()
        try:
            response = stub.AcceptRide(uber_pb2.AcceptRideRequest(ride_id=ride_id), metadata=self.metadata)
            print(response.message)
        except grpc.RpcError as e:
            print(f"Error accepting ride: {e}")

    def reject_ride(self, ride_id):
        print(f"Rejecting ride with ID {ride_id}...")
        self.timer_event.set()
        stub = self.get_stub()
        try:
            response = stub.RejectRide(uber_pb2.RejectRideRequest(ride_id=ride_id), metadata=self.metadata)
            print(response.message)
        except grpc.RpcError as e:
            print(f"Error rejecting ride: {e}")

    def listen_for_rider_notifications(self):
        stub = self.get_stub()
        for notification in stub.RiderNotificationService(uber_pb2.NotificationRequest(id=self.registered_id)):
            print("Notification received:", notification.notification)

    def request_ride(self):
        pickup = input("Enter pickup location: ")
        destination = input("Enter destination: ")
        ride_request = uber_pb2.RideRequest(rider_id=self.registered_id, pickup=pickup, destination=destination)

        stub = self.get_stub()
        try:
            response = stub.RequestRide(ride_request, metadata=self.metadata)
            print("Ride Request Response:", response.message)
        except grpc.RpcError as e:
            print(f"Error requesting ride: {e}")

    def complete_ride(self, ride_request_id):
        stub = self.get_stub()
        try:
            ride_request = uber_pb2.CompleteRideRequest(ride_id=ride_request_id, driver_id=self.registered_id)
            response = stub.CompleteRide(ride_request, metadata=self.metadata)
            print(response.message)
        except grpc.RpcError as e:
            print(f"Error completing ride: {e}")

    def get_status(self):
        print("Fetching ride status...")
        stub = self.get_stub()
        try:
            response = stub.GetRideStatus(uber_pb2.StatusRequest(rider_id=self.registered_id), metadata=self.metadata)

            if response.empty:
                print("No active or completed rides found.")
            else:
                print("\n--- Ride Status ---")
                print(f"Driver Name    : {response.driver_name}")
                print(f"Pickup Location: {response.pickup}")
                print(f"Destination    : {response.destination}")
                print(f"Ride Status    : {response.status}")
                print("-------------------\n")
        except grpc.RpcError as e:
            print(f"Error while fetching ride status: {e.code()}: {e.details()}")

    def exit(self):
        stub = self.get_stub()
        try:
            response = stub.Exit(uber_pb2.ExitRequest(role=self.role, registered_id=self.registered_id))
            print(response.message)
        except grpc.RpcError as e:
            print(f"Error while exiting: {e.code()}: {e.details()}")

    def run(self):
        if len(sys.argv) != 3:
            print("Usage: python client.py <driver|rider> <name>")
            return

        self.role = sys.argv[1].lower()
        name = sys.argv[2]

        if self.role == 'driver':
            self.register_driver(name)
            notification_thread = threading.Thread(target=self.listen_for_driver_notifications)
            notification_thread.daemon = True
            notification_thread.start()
        elif self.role == 'rider':
            self.register_rider(name)
            notification_thread = threading.Thread(target=self.listen_for_rider_notifications)
            notification_thread.daemon = True
            notification_thread.start()
        else:
            print("Invalid role. Use 'driver' or 'rider'.")
            return

        while not self.exit_event.is_set():
            if self.role == "rider":
                print("1. Request Ride")
                print("2. Get Status")
                print("3. Exit")

                choice = input("Choose an option: ")

                if choice == "1":
                    self.request_ride()
                elif choice == "2":
                    self.get_status()
                elif choice == "3":
                    print("Exiting...")
                    self.exit()
                    self.exit_event.set()
                    break
                else:
                    print("Invalid option. Please try again.")
            else:
                print("1. Exit")
                choice = input("Choose an option or wait for notification: ")
                if choice == "1":
                    print("Exiting...")
                    self.exit()
                    self.exit_event.set()
                    break
                elif choice == "2":
                    self.accept_ride(self.ride_request_id)
                    while(True):
                        com = input("Enter 4 to complete ride: ")
                        if com == "4":
                            self.complete_ride(self.ride_request_id)
                            break;
                elif choice == "3":
                        self.reject_ride(stub, self.ride_request_id)
                        print("Cancelling ride")

if __name__ == '__main__':
    client = RideClient()
    client.run()