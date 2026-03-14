from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
import secrets
import os
from pathlib import Path
from database import engine, get_db
from models import Base, User, Role, Product, Category, Zone, Operation, OperationItem, Supplier, Customer


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="WMS - Warehouse Management System",
    description="Система управления складскими операциями",
    version="2.0.0"
)

app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def check_auth(request: Request):
    return request.session.get('logged_in', False)


def get_current_user(request: Request, db: Session):
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if check_auth(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    error = request.session.pop('error', None)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
async def login_post(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()

    if not user or user.password != password:
        request.session['error'] = "Неверный email или пароль"
        return RedirectResponse(url="/login", status_code=303)

    if not user.is_active:
        request.session['error'] = "Аккаунт деактивирован"
        return RedirectResponse(url="/login", status_code=303)

    request.session['logged_in'] = True
    request.session['user_id'] = user.id
    request.session['user_email'] = user.email

    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
        request: Request,
        tab: str = "overview",
        db: Session = Depends(get_db)
):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    total_products = db.query(Product).filter(Product.is_active == True).count()
    operations_today = db.query(Operation).filter(
        Operation.operation_date >= datetime.now().date()
    ).count()
    pending_operations = db.query(Operation).filter(
        Operation.status.in_(['pending', 'processing'])
    ).count()
    active_users = db.query(User).filter(User.is_active == True).count()

    stats = [
        {'value': f"{total_products:,}", 'label': 'Всего товаров', 'icon': '📊', 'color': 'blue'},
        {'value': str(operations_today), 'label': 'Операций сегодня', 'icon': '✓', 'color': 'green'},
        {'value': str(pending_operations), 'label': 'Требуют внимания', 'icon': '⚠️', 'color': 'orange'},
        {'value': str(active_users), 'label': 'Активных сотрудников', 'icon': '👥', 'color': 'purple'}
    ]

    db_operations = db.query(Operation).order_by(desc(Operation.operation_date)).limit(5).all()

    operations = []
    for op in db_operations:
        status_map = {
            'completed': {'status': 'success', 'text': 'Завершено'},
            'processing': {'status': 'processing', 'text': 'В процессе'},
            'pending': {'status': 'pending', 'text': 'Ожидает'}
        }
        status_info = status_map.get(op.status, {'status': 'pending', 'text': 'Неизвестно'})

        type_map = {
            'acceptance': 'Приемка товара',
            'shipment': 'Отгрузка заказа',
            'movement': 'Перемещение товара',
            'inventory': 'Инвентаризация'
        }
        title = type_map.get(op.operation_type, 'Операция')

        desc_parts = []
        if op.supplier_customer:
            desc_parts.append(op.supplier_customer)
        if op.notes:
            desc_parts.append(op.notes)
        desc_parts.append(op.operation_date.strftime('%d.%m.%Y, %H:%M'))

        operations.append({
            'id': op.operation_number,
            'title': title,
            'desc': ' • '.join(desc_parts),
            'status': status_info['status'],
            'status_text': status_info['text']
        })

    quick_actions = [
        {'title': 'Приемка товара', 'desc': 'Добавить новое поступление', 'icon': '📥', 'color': 'blue'},
        {'title': 'Отгрузка', 'desc': 'Оформить отправку товара', 'icon': '📤', 'color': 'green'},
        {'title': 'Перемещение', 'desc': 'Переместить между зонами', 'icon': '🔄', 'color': 'purple'},
        {'title': 'Инвентаризация', 'desc': 'Провести учет остатков', 'icon': '📋', 'color': 'orange'},
        {'title': 'Отчеты', 'desc': 'Сформировать отчет', 'icon': '📊', 'color': 'indigo'}
    ]

    user_data = {
        'name': current_user.full_name,
        'role': current_user.role.name if current_user.role else 'Не назначена',
        'initials': ''.join([word[0] for word in current_user.full_name.split()[:2]]),
        'email': current_user.email,
        'phone': current_user.phone or 'Не указан',
        'employee_id': current_user.employee_id
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user_data,
        "current_tab": tab,
        "stats": stats,
        "operations": operations,
        "quick_actions": quick_actions
    })

@app.get("/api/users")
async def get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"users": [{"id": u.id, "email": u.email, "full_name": u.full_name} for u in users]}


@app.get("/api/users/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "phone": user.phone}


@app.post("/api/users")
async def create_user(
        email: str = Form(...),
        password: str = Form(...),
        full_name: str = Form(...),
        phone: str = Form(None),
        role_id: int = Form(2),
        db: Session = Depends(get_db)
):
    last_user = db.query(User).order_by(desc(User.id)).first()
    employee_number = (last_user.id + 1) if last_user else 1
    employee_id = f"EMP-{employee_number:05d}"

    user = User(
        email=email,
        password=password,
        full_name=full_name,
        phone=phone,
        role_id=role_id,
        employee_id=employee_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Пользователь создан", "user_id": user.id}

@app.get("/api/products")
async def get_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True).offset(skip).limit(limit).all()
    return {
        "products": [{"id": p.id, "name": p.name, "quantity": p.quantity, "price": float(p.price)} for p in products]}


@app.get("/api/products/{product_id}")
async def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return {
        "id": product.id,
        "name": product.name,
        "article": product.article,
        "quantity": product.quantity,
        "price": float(product.price),
        "unit": product.unit
    }

@app.get("/api/operations")
async def get_operations(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    operations = db.query(Operation).order_by(desc(Operation.operation_date)).offset(skip).limit(limit).all()
    return {"operations": [
        {
            "id": op.id,
            "number": op.operation_number,
            "type": op.operation_type,
            "status": op.status,
            "date": op.operation_date.isoformat()
        } for op in operations
    ]}


@app.get("/api/operations/{operation_id}")
async def get_operation(operation_id: int, db: Session = Depends(get_db)):
    operation = db.query(Operation).filter(Operation.id == operation_id).first()
    if not operation:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    return {
        "id": operation.id,
        "number": operation.operation_number,
        "type": operation.operation_type,
        "status": operation.status,
        "supplier_customer": operation.supplier_customer,
        "total_amount": float(operation.total_amount),
        "notes": operation.notes,
        "date": operation.operation_date.isoformat()
    }

@app.get("/api/categories")
async def get_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).all()
    return {"categories": [{"id": c.id, "name": c.name, "description": c.description} for c in categories]}

@app.get("/api/zones")
async def get_zones(db: Session = Depends(get_db)):
    zones = db.query(Zone).filter(Zone.is_active == True).all()
    return {"zones": [{"id": z.id, "code": z.code, "name": z.name, "capacity": z.capacity} for z in zones]}

@app.get("/api/roles")
async def get_roles(db: Session = Depends(get_db)):
    roles = db.query(Role).all()
    return {"roles": [{"id": r.id, "name": r.name, "description": r.description} for r in roles]}


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(get_db)):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    total_operations = db.query(Operation).filter(Operation.user_id == current_user.id).count()
    completed_operations = db.query(Operation).filter(
        Operation.user_id == current_user.id,
        Operation.status == 'completed'
    ).count()

    accuracy = round((completed_operations / total_operations * 100), 1) if total_operations > 0 else 0

    user_data = {
        'id': current_user.id,
        'name': current_user.full_name,
        'role': current_user.role.name if current_user.role else 'Не назначена',
        'initials': ''.join([word[0] for word in current_user.full_name.split()[:2]]),
        'email': current_user.email,
        'phone': current_user.phone or '',
        'employee_id': current_user.employee_id,
        'start_date': current_user.start_date.strftime('%d.%m.%Y') if current_user.start_date else '',
        'avatar': current_user.avatar or None,
        'total_operations': total_operations,
        'completed_operations': completed_operations,
        'accuracy': accuracy
    }

    success = request.session.pop('success', None)
    error = request.session.pop('error', None)

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user_data,
        "success": success,
        "error": error
    })


@app.post("/profile/update")
async def profile_update(
        request: Request,
        full_name: str = Form(...),
        email: str = Form(...),
        phone: str = Form(None),
        avatar: UploadFile = File(None),
        db: Session = Depends(get_db)
):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    current_user.full_name = full_name
    current_user.email = email
    current_user.phone = phone

    if avatar and avatar.filename:
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        file_ext = os.path.splitext(avatar.filename)[1].lower()

        if file_ext not in allowed_extensions:
            request.session['error'] = 'Неверный формат файла. Разрешены: JPG, PNG, GIF, WEBP'
            return RedirectResponse(url="/profile", status_code=303)

        filename = f"user_{current_user.id}_{secrets.token_hex(8)}{file_ext}"
        filepath = Path("static/avatars") / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        if current_user.avatar:
            old_avatar_path = Path(current_user.avatar.lstrip('/'))
            if old_avatar_path.exists():
                old_avatar_path.unlink()

        with open(filepath, "wb") as f:
            content = await avatar.read()
            f.write(content)
        current_user.avatar = f"/static/avatars/{filename}"
    db.commit()

    request.session['success'] = 'Профиль успешно обновлён!'
    return RedirectResponse(url="/profile", status_code=303)


@app.post("/profile/delete-avatar")
async def delete_avatar(request: Request, db: Session = Depends(get_db)):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    if current_user.avatar:
        avatar_path = Path(current_user.avatar.lstrip('/'))
        if avatar_path.exists():
            avatar_path.unlink()

        current_user.avatar = None
        db.commit()

        request.session['success'] = 'Аватарка удалена'

    return RedirectResponse(url="/profile", status_code=303)


@app.get("/acceptance", response_class=HTMLResponse)
async def acceptance_page(request: Request, db: Session = Depends(get_db)):
    """Страница приёмки товара"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    # Получаем список товаров, зон и ПОСТАВЩИКОВ
    products = db.query(Product).filter(Product.is_active == True).all()
    zones = db.query(Zone).filter(Zone.is_active == True).all()
    suppliers = db.query(Supplier).filter(Supplier.is_active == True).all()  # ← ДОБАВИЛИ!

    # Генерируем следующий номер операции
    last_operation = db.query(Operation).filter(
        Operation.operation_type == 'acceptance'
    ).order_by(desc(Operation.id)).first()

    if last_operation and last_operation.operation_number:
        try:
            last_num = int(last_operation.operation_number.split('-')[1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1

    next_number = f"ПР-{next_num:04d}"
    today = datetime.now().strftime('%Y-%m-%d')

    user_data = {
        'name': current_user.full_name,
        'role': current_user.role.name if current_user.role else 'Не назначена',
        'initials': ''.join([word[0] for word in current_user.full_name.split()[:2]])
    }

    success = request.session.pop('success', None)
    error = request.session.pop('error', None)

    return templates.TemplateResponse("acceptance.html", {
        "request": request,
        "user": user_data,
        "products": products,
        "zones": zones,
        "suppliers": suppliers,
        "next_number": next_number,
        "today": today,
        "success": success,
        "error": error
    })

@app.post("/acceptance/create")
async def acceptance_create(request: Request, db: Session = Depends(get_db)):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    form_data = await request.form()

    operation_number = form_data.get('operation_number')
    operation_date = form_data.get('operation_date')
    supplier = form_data.get('supplier')
    notes = form_data.get('notes', '')

    try:
        operation = Operation(
            operation_type='acceptance',
            operation_number=operation_number,
            status='completed',
            user_id=current_user.id,
            supplier_customer=supplier,
            notes=notes,
            operation_date=datetime.strptime(operation_date, '%Y-%m-%d'),
            completed_at=datetime.now()
        )

        db.add(operation)
        db.flush()

        total_amount = 0
        product_indices = set()

        for key in form_data.keys():
            if key.startswith('products[') and key.endswith('][product_id]'):
                index = key.split('[')[1].split(']')[0]
                product_indices.add(index)

        for index in product_indices:
            product_id = form_data.get(f'products[{index}][product_id]')
            quantity = form_data.get(f'products[{index}][quantity]')
            price = form_data.get(f'products[{index}][price]')
            zone_id = form_data.get(f'products[{index}][zone_id]')

            if not all([product_id, quantity, price, zone_id]):
                continue

            product_id = int(product_id)
            quantity = int(quantity)
            price = float(price)
            zone_id = int(zone_id)

            operation_item = OperationItem(
                operation_id=operation.id,
                product_id=product_id,
                quantity=quantity,
                price=price,
                to_zone_id=zone_id
            )
            db.add(operation_item)
            product = db.query(Product).filter(Product.id == product_id).first()
            if product:
                product.quantity += quantity
                product.zone_id = zone_id
            total_amount += quantity * price
        operation.total_amount = total_amount
        db.commit()

        request.session[
            'success'] = f'Приёмка {operation_number} успешно оформлена! Принято товаров на сумму {total_amount:,.2f} ₽'
        return RedirectResponse(url="/acceptance", status_code=303)

    except Exception as e:
        db.rollback()
        request.session['error'] = f'Ошибка при создании приёмки: {str(e)}'
        return RedirectResponse(url="/acceptance", status_code=303)


@app.get("/shipment", response_class=HTMLResponse)
async def shipment_page(request: Request, db: Session = Depends(get_db)):
    """Страница отгрузки товара"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    # Получаем товары (только те, что есть в наличии)
    products = db.query(Product).filter(
        Product.is_active == True,
        Product.quantity > 0
    ).all()

    # Получаем заказчиков
    customers = db.query(Customer).filter(Customer.is_active == True).all()

    # Генерируем следующий номер операции
    last_operation = db.query(Operation).filter(
        Operation.operation_type == 'shipment'
    ).order_by(desc(Operation.id)).first()

    if last_operation and last_operation.operation_number:
        try:
            last_num = int(last_operation.operation_number.split('-')[1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1

    next_number = f"ОТ-{next_num:04d}"
    today = datetime.now().strftime('%Y-%m-%d')

    user_data = {
        'name': current_user.full_name,
        'role': current_user.role.name if current_user.role else 'Не назначена',
        'initials': ''.join([word[0] for word in current_user.full_name.split()[:2]])
    }

    success = request.session.pop('success', None)
    error = request.session.pop('error', None)

    return templates.TemplateResponse("shipment.html", {
        "request": request,
        "user": user_data,
        "products": products,
        "customers": customers,
        "next_number": next_number,
        "today": today,
        "success": success,
        "error": error
    })


@app.post("/shipment/create")
async def shipment_create(request: Request, db: Session = Depends(get_db)):
    """Создание операции отгрузки"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    current_user = get_current_user(request, db)
    if not current_user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    # Получаем данные формы
    form_data = await request.form()

    operation_number = form_data.get('operation_number')
    operation_date = form_data.get('operation_date')
    customer = form_data.get('customer')
    delivery_address = form_data.get('delivery_address')
    notes = form_data.get('notes', '')

    try:
        # Создаём операцию
        operation = Operation(
            operation_type='shipment',
            operation_number=operation_number,
            status='completed',
            user_id=current_user.id,
            supplier_customer=f"{customer} | {delivery_address}",
            notes=notes,
            operation_date=datetime.strptime(operation_date, '%Y-%m-%d'),
            completed_at=datetime.now()
        )

        db.add(operation)
        db.flush()

        # Обрабатываем товары
        total_amount = 0
        product_indices = set()

        for key in form_data.keys():
            if key.startswith('products[') and key.endswith('][product_id]'):
                index = key.split('[')[1].split(']')[0]
                product_indices.add(index)

        for index in product_indices:
            product_id = form_data.get(f'products[{index}][product_id]')
            quantity = form_data.get(f'products[{index}][quantity]')
            price = form_data.get(f'products[{index}][price]')

            if not all([product_id, quantity, price]):
                continue

            product_id = int(product_id)
            quantity = int(quantity)
            price = float(price)

            # Проверяем наличие товара
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                raise Exception(f'Товар с ID {product_id} не найден')

            if product.quantity < quantity:
                raise Exception(f'Недостаточно товара "{product.name}" на складе. Доступно: {product.quantity}')

            # Создаём запись в operation_items
            operation_item = OperationItem(
                operation_id=operation.id,
                product_id=product_id,
                quantity=quantity,
                price=price,
                from_zone_id=product.zone_id  # Запоминаем из какой зоны отгрузили
            )
            db.add(operation_item)

            product.quantity -= quantity

            total_amount += quantity * price

        operation.total_amount = total_amount

        db.commit()

        request.session[
            'success'] = f'Отгрузка {operation_number} успешно оформлена! Отгружено товаров на сумму {total_amount:,.2f} ₽'
        return RedirectResponse(url="/shipment", status_code=303)

    except Exception as e:
        db.rollback()
        request.session['error'] = f'Ошибка при создании отгрузки: {str(e)}'
        return RedirectResponse(url="/shipment", status_code=303)


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("🚀 Запуск WMS с PostgreSQL")
    print("=" * 60)
    print(f"🌐 Приложение: http://localhost:8000")
    print(f"📚 API документация: http://localhost:8000/docs")
    print(f"🗄️  База данных: PostgreSQL (wms_db)")
    print("")
    print("👤 Тестовый вход:")
    print("   Email: admin@wms.com")
    print("   Пароль: admin123")
    print("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)