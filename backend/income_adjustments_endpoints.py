# =============================================
# MANUEL GELİR AYARLAMALARI - INCOME ADJUSTMENTS
# =============================================

@app.route('/api/admin/income-adjustments', methods=['POST'])
@token_required
def add_income_adjustment():
    """Manuel gelir ayarlaması ekle - SADECE SUPER_ADMIN"""
    
    # Sadece super_admin ekleyebilir
    if request.staff_role != 'super_admin':
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    data = request.get_json()
    amount = data.get('amount')
    description = data.get('description')
    adjustment_date = data.get('adjustment_date')
    
    # Validasyon
    if not all([amount, description, adjustment_date]):
        return jsonify({'success': False, 'message': 'Tüm alanlar gerekli'}), 400
    
    try:
        amount = float(amount)
    except ValueError:
        return jsonify({'success': False, 'message': 'Geçersiz miktar'}), 400
    
    if not description.strip():
        return jsonify({'success': False, 'message': 'Açıklama boş olamaz'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO income_adjustments (amount, description, adjustment_date, created_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id, amount, description, adjustment_date, created_at
        """, (amount, description, adjustment_date, request.staff_id))
        
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        
        adjustment = {
            'id': result[0],
            'amount': float(result[1]),
            'description': result[2],
            'adjustment_date': result[3].strftime('%Y-%m-%d'),
            'created_at': result[4].isoformat()
        }
        
        logger.info(f"Gelir ayarlaması eklendi: {result[0]} by staff {request.staff_id}")
        
        return jsonify({
            'success': True,
            'message': 'Gelir ayarlaması başarıyla eklendi',
            'adjustment': adjustment
        })
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"add_income_adjustment hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlama eklenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/income-adjustments', methods=['GET'])
@token_required
def get_income_adjustments():
    """Belirli bir ay/yıldaki gelir ayarlamalarını listele - SADECE SUPER_ADMIN"""
    
    # Sadece super_admin görebilir
    if request.staff_role != 'super_admin':
        return jsonify({'success': False, 'message': 'Bu rapora erişim yetkiniz yok'}), 403
    
    month = request.args.get('month')
    year = request.args.get('year')
    
    if not month:
        month = datetime.now().month
    if not year:
        year = datetime.now().year
    
    month = int(month)
    year = int(year)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                ia.id,
                ia.amount,
                ia.description,
                ia.adjustment_date,
                s.first_name || ' ' || s.last_name as created_by_name,
                ia.created_at
            FROM income_adjustments ia
            LEFT JOIN artists s ON ia.created_by = s.id
            WHERE EXTRACT(MONTH FROM ia.adjustment_date) = %s
              AND EXTRACT(YEAR FROM ia.adjustment_date) = %s
            ORDER BY ia.adjustment_date DESC, ia.created_at DESC
        """, (month, year))
        
        rows = cursor.fetchall()
        adjustments = []
        total_adjustments = 0
        
        for row in rows:
            adjustment = {
                'id': row[0],
                'amount': float(row[1]),
                'description': row[2],
                'adjustment_date': row[3].strftime('%d.%m.%Y'),
                'created_by_name': row[4] or 'Bilinmiyor',
                'created_at': row[5].isoformat()
            }
            adjustments.append(adjustment)
            total_adjustments += float(row[1])
        
        cursor.close()
        
        logger.info(f"Gelir ayarlamaları listelendi: {month}/{year}")
        
        return jsonify({
            'success': True,
            'adjustments': adjustments,
            'total_adjustments': total_adjustments,
            'month': month,
            'year': year
        })
        
    except Exception as e:
        logger.error(f"get_income_adjustments hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlamalar alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/income-adjustments/<int:adjustment_id>', methods=['DELETE'])
@token_required
def delete_income_adjustment(adjustment_id):
    """Gelir ayarlamasını sil - SADECE SUPER_ADMIN"""
    
    # Sadece super_admin silebilir
    if request.staff_role != 'super_admin':
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Önce kayıt var mı kontrol et
        cursor.execute("SELECT id FROM income_adjustments WHERE id = %s", (adjustment_id,))
        if not cursor.fetchone():
            cursor.close()
            return jsonify({'success': False, 'message': 'Ayarlama bulunamadı'}), 404
        
        cursor.execute("DELETE FROM income_adjustments WHERE id = %s", (adjustment_id,))
        conn.commit()
        cursor.close()
        
        logger.info(f"Gelir ayarlaması silindi: {adjustment_id} by staff {request.staff_id}")
        
        return jsonify({
            'success': True,
            'message': 'Gelir ayarlaması başarıyla silindi'
        })
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_income_adjustment hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlama silinemedi'}), 500
    finally:
        release_db_connection(conn)
