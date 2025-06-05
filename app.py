from functools import wraps
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import db, User, Product, Request, Order
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secure-secret-key-1234567890'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///meditrack.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form['role']

        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('signup'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'danger')
            return redirect(url_for('signup'))

        user = User(name=name, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for(f"{user.role.lower()}_dashboard"))
        else:
            flash('Invalid email or password!', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Supplier Routes
@app.route('/supplier_dashboard')
@login_required
def supplier_dashboard():
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    product_count = Product.query.filter_by(supplier_id=current_user.id).count()
    request_count = Request.query.filter_by(target_id=current_user.id, status='Pending').count()
    low_stock = Product.query.filter_by(supplier_id=current_user.id).filter(Product.quantity < 10).count()
    return render_template('supplier_dashboard.html', product_count=product_count, request_count=request_count, low_stock=low_stock)

@app.route('/supplier_products', methods=['GET', 'POST'])
@login_required
def supplier_products():
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    if request.method == 'POST':
        product_name = request.form['product_name']
        quantity = int(request.form['quantity'])
        expiry_date = datetime.strptime(request.form['expiry_date'], '%Y-%m-%d').date()
        if quantity < 0:
            flash('Quantity cannot be negative!', 'danger')
            return redirect(url_for('supplier_products'))
        product = Product(name=product_name, quantity=quantity, expiry_date=expiry_date, supplier_id=current_user.id)
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully!', 'success')
    products = Product.query.filter_by(supplier_id=current_user.id).all()
    return render_template('supplier_products.html', products=products)

@app.route('/supplier_requests')
@login_required
def supplier_requests():
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    requests = Request.query.filter_by(target_id=current_user.id).all()
    requests_data = [
        {
            'id': req.id,
            'product_name': req.product.name,
            'quantity': req.quantity,
            'pharmacy_name': req.customer.name,
            'status': req.status
        } for req in requests
    ]
    return render_template('supplier_requests.html', requests=requests_data)

@app.route('/supplier_orders')
@login_required
def supplier_orders():
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    orders = Order.query.filter_by(supplier_id=current_user.id).all()
    orders_data = [
        {
            'id': order.id,
            'product_name': order.product.name,
            'quantity': order.quantity,
            'pharmacy_name': order.requester.name,
            'status': order.status
        } for order in orders
    ]
    return render_template('supplier_orders.html', orders=orders_data)

@app.route('/accept_request/<int:request_id>')
@login_required
def accept_request(request_id):
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    req = Request.query.get_or_404(request_id)
    if req.target_id == current_user.id and req.status == 'Pending':
        product = Product.query.filter_by(name=req.product.name, supplier_id=current_user.id).first()
        if not product or product.quantity < req.quantity:
            flash('Insufficient stock or product not found!', 'danger')
            return redirect(url_for('supplier_requests'))
        req.status = 'Accepted'
        product.quantity -= req.quantity  # Deduct from Supplier's stock
        # Check if the Pharmacy already has this product in their inventory
        pharmacy_product = Product.query.filter_by(supplier_id=req.customer_id, name=req.product.name).first()
        if pharmacy_product:
            # Update quantity if product exists
            pharmacy_product.quantity += req.quantity
        else:
            # Add new product to Pharmacy's inventory
            new_pharmacy_product = Product(
                name=req.product.name,
                supplier_id=req.customer_id,  # Pharmacy's ID
                quantity=req.quantity,
                expiry_date=req.product.expiry_date,
                supplier=req.customer  # Link to the Pharmacy user
            )
            db.session.add(new_pharmacy_product)
        order = Order(
            request_id=req.id,
            supplier_id=current_user.id,
            requester_id=req.customer_id,
            product_id=req.product_id,
            quantity=req.quantity,
            status='Processing'
        )
        db.session.add(order)
        db.session.commit()
        flash('Request accepted and order created! Product added to Pharmacy inventory.', 'success')
    return redirect(url_for('supplier_requests'))
@app.route('/reject_request/<int:request_id>')
@login_required
def reject_request(request_id):
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    req = Request.query.get_or_404(request_id)
    if req.target_id == current_user.id:
        req.status = 'Rejected'
        db.session.commit()
        flash('Request rejected!', 'success')
    return redirect(url_for('supplier_requests'))

@app.route('/ship_order/<int:order_id>')
@login_required
def ship_order(order_id):
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    order = Order.query.get_or_404(order_id)
    if order.supplier_id == current_user.id and order.status == 'Processing':
        order.status = 'Shipped'
        db.session.commit()
        flash('Order marked as shipped!', 'success')
    return redirect(url_for('supplier_orders'))

@app.route('/complete_order/<int:order_id>')
@login_required
def complete_order(order_id):
    if current_user.role != 'Supplier':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    order = Order.query.get_or_404(order_id)
    if order.supplier_id == current_user.id and order.status == 'Shipped':
        order.status = 'Completed'
        db.session.commit()
        flash('Order marked as completed!', 'success')
    return redirect(url_for('supplier_orders'))

# Pharmacy Routes
@app.route('/pharmacy_dashboard')
@login_required
def pharmacy_dashboard():
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    product_count = Product.query.count()
    request_count = Request.query.filter_by(target_id=current_user.id, status='Pending').count()
    order_count = Order.query.filter_by(requester_id=current_user.id).count()
    return render_template('pharmacy_dashboard.html', product_count=product_count, request_count=request_count, order_count=order_count)

@app.route('/pharmacy_products')
@login_required
def pharmacy_products():
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    # Fetch completed orders for this pharmacy
    completed_orders = Order.query.filter_by(requester_id=current_user.id, status='Completed').all()
    
    # Aggregate products and their quantities
    product_quantities = {}
    for order in completed_orders:
        product = order.product
        product_id = product.id
        if product_id in product_quantities:
            product_quantities[product_id]['quantity'] += order.quantity
        else:
            product_quantities[product_id] = {
                'id': product.id,
                'name': product.name,
                'quantity': order.quantity,
                'supplier_name': product.supplier.name
            }
    
    # Convert to list for the template
    products_data = list(product_quantities.values())
    return render_template('pharmacy_products.html', products=products_data)

@app.route('/pharmacy_orders', methods=['GET', 'POST'])
@login_required
def pharmacy_orders():
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        supplier_id = int(request.form['supplier_id'])
        if quantity < 0:
            flash('Quantity cannot be negative!', 'danger')
            return redirect(url_for('pharmacy_orders'))
        product = Product.query.get_or_404(product_id)
        req = Request(
            product_id=product_id,
            customer_id=current_user.id,
            customer_name=current_user.name,
            target_id=supplier_id,
            quantity=quantity
        )
        db.session.add(req)
        db.session.commit()
        flash('Request sent successfully!', 'success')
    products = Product.query.all()
    orders = Order.query.filter_by(requester_id=current_user.id).all()
    orders_data = [
        {
            'id': order.id,
            'product_name': order.product.name,
            'quantity': order.quantity,
            'supplier_name': order.supplier.name,
            'status': order.status
        } for order in orders
    ]
    suppliers = User.query.filter_by(role='Supplier').all()
    return render_template('pharmacy_orders.html', orders=orders_data, suppliers=suppliers, products=products)

@app.route('/pharmacy_requests')
@login_required
def pharmacy_requests():
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    requests = Request.query.filter_by(target_id=current_user.id).all()
    requests_data = [
        {
            'id': req.id,
            'product_name': req.product.name,
            'quantity': req.quantity,
            'customer_name': req.customer.name,
            'status': req.status
        } for req in requests
    ]
    return render_template('pharmacy_requests.html', requests=requests_data)

@app.route('/pharmacy_accept_request/<int:request_id>')
@login_required
def pharmacy_accept_request(request_id):
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    req = Request.query.get_or_404(request_id)
    if req.target_id == current_user.id:
        req.status = 'Accepted'
        order = Order(
            request_id=req.id,
            supplier_id=req.target_id,
            requester_id=req.customer_id,
            product_id=req.product_id,
            quantity=req.quantity,
            status='Processing'
        )
        db.session.add(order)
        db.session.commit()
        flash('Request accepted and order created!', 'success')
    return redirect(url_for('pharmacy_requests'))

@app.route('/pharmacy_reject_request/<int:request_id>')
@login_required
def pharmacy_reject_request(request_id):
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    req = Request.query.get_or_404(request_id)
    if req.target_id == current_user.id:
        req.status = 'Rejected'
        db.session.commit()
        flash('Request rejected!', 'success')
    return redirect(url_for('pharmacy_requests'))

@app.route('/pharmacy_ship_order/<int:order_id>')
@login_required
def pharmacy_ship_order(order_id):
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    order = Order.query.get_or_404(order_id)
    if order.supplier_id == current_user.id and order.status == 'Processing':
        order.status = 'Shipped'
        db.session.commit()
        flash('Order marked as shipped!', 'success')
    return redirect(url_for('pharmacy_requests'))

@app.route('/pharmacy_complete_order/<int:order_id>')
@login_required
def pharmacy_complete_order(order_id):
    if current_user.role != 'Pharmacy':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    order = Order.query.get_or_404(order_id)
    if order.supplier_id == current_user.id and order.status == 'Shipped':
        order.status = 'Completed'
        db.session.commit()
        flash('Order marked as completed!', 'success')
    return redirect(url_for('pharmacy_requests'))

# Customer Routes
@app.route('/customer_dashboard')
@login_required
def customer_dashboard():
    if current_user.role != 'Customer':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    product_count = Product.query.count()
    order_count = Order.query.filter_by(requester_id=current_user.id).count()
    return render_template('customer_dashboard.html', product_count=product_count, order_count=order_count)

def role_required(role):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role != role:
                flash('Access denied.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/customer_order_products', methods=['GET', 'POST'])
@login_required
@role_required('Customer')
def customer_order_products():
    if request.method == 'POST':
        pharmacy_id = request.form.get('pharmacy_id')
        product_id = request.form.get('product_id')
        quantity = request.form.get('quantity')
        product = Product.query.get(product_id)
        pharmacy = User.query.get(pharmacy_id)
        if product and quantity and pharmacy and pharmacy.role == 'Pharmacy':
            if product.supplier_id == int(pharmacy_id) and product.quantity >= int(quantity):
                new_request = Request(
                    product_id=product.id,
                    product_name=product.name,
                    quantity=int(quantity),
                    customer_id=current_user.id,
                    customer_name=current_user.name,
                    target_id=product.supplier_id,  # Pharmacy's ID
                    pharmacy_name=pharmacy.name,
                    status='Pending'
                )
                db.session.add(new_request)
                db.session.commit()
                flash('Product order placed successfully!', 'success')
                return redirect(url_for('customer_order_products'))
            else:
                flash('Failed to place order: Product not available or insufficient stock.', 'danger')
        else:
            flash('Failed to place order: Invalid pharmacy or product.', 'danger')
    # Fetch all Pharmacies
    pharmacies = User.query.filter_by(role='Pharmacy').all()
    # Fetch previous requests made by the Customer
    requests = Request.query.filter_by(customer_id=current_user.id).all()
    # Fetch orders for each request
    request_orders = {}
    for req in requests:
        order = Order.query.filter_by(request_id=req.id).first()
        request_orders[req.id] = order
    return render_template('customer_order_products.html', pharmacies=pharmacies, requests=requests, request_orders=request_orders)

@app.route('/get_pharmacy_products/<int:pharmacy_id>', methods=['GET'])
@login_required
@role_required('Customer')
def get_pharmacy_products(pharmacy_id):
    pharmacy = User.query.get(pharmacy_id)
    if pharmacy and pharmacy.role == 'Pharmacy':
        products = Product.query.filter_by(supplier_id=pharmacy_id).filter(Product.quantity > 0).all()
        products_data = [
            {'id': product.id, 'name': f"{product.name} (Available: {product.quantity})"}
            for product in products
        ]
        return jsonify(products_data)
    return jsonify([])
@app.route('/customer_order_tracking')
@login_required
def customer_order_tracking():
    if current_user.role != 'Customer':
        return redirect(url_for(f"{current_user.role.lower()}_dashboard"))
    orders = Order.query.filter_by(requester_id=current_user.id).all()
    orders_data = [
        {
            'id': order.id,
            'product_name': order.product.name,
            'quantity': order.quantity,
            'pharmacy_name': order.supplier.name,
            'status': order.status
        } for order in orders
    ]
    return render_template('customer_order_tracking.html', orders=orders_data)

if __name__ == '__main__':
    app.run(debug=True)