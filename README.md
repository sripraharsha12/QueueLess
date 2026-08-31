# QueueLess

## Smart Digital Queue Management System

QueueLess is a lightweight digital queue management system that helps customers join a queue remotely, track their position and estimated waiting time, receive reminders and notifications, and avoid standing in physical lines.

## Problem

Traditional queues make customers wait in crowded spaces without knowing how long their turn will take.

QueueLess solves this by allowing customers to join the queue digitally and monitor their queue status in real time.

## Features

### Customer Side
- Join a queue digitally
- Select a service
- Receive a queue token
- View people ahead
- View estimated waiting time
- View active counters
- Set reminders for the upcoming turn
- Receive in-app notifications
- See when it is their turn

### Management Side
- View the current queue
- Monitor waiting and serving customers
- Manage counters
- Call customers
- Complete services
- Mark customers as no-show
- View queue analytics

## QR-Based Access

Customers can access QueueLess by scanning the QueueLess QR code.

The QR code opens the customer page:

https://queueless-vrww.onrender.com/

## Live Demo

Customer:
https://queueless-vrww.onrender.com/

Management:
https://queueless-vrww.onrender.com/management

## How It Works

Customer scans QR
↓
Join Queue
↓
Receive Token
↓
View Position + ETA
↓
Set Reminder
↓
Management Calls Customer
↓
Customer Gets Notification
↓
Service Completed

## Technology

- Python
- SQLite
- HTML
- CSS
- Python Standard Library

## Project Structure

QueueLess/
├── .gitignore
├── README.md
├── app.py
└── assets/
    └── QueueLess_QR.png

## How to Run Locally

```bash
python app.py
