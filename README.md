# CRM Base Application

## Database Management

### Development Environment
- Database initialization and migrations only run in development environment
- Local database path: `sqlite:///crm_multi.db`
- To initialize database:
  ```bash
  export FLASK_ENV=development
  python database_setup.py
  ```

### Production Environment (Render)
- Database is stored on a persistent disk at `/data/crm_multi.db`
- Database path: `sqlite:////data/crm_multi.db`
- Database initialization is blocked in production/staging
- Daily backups with 7-day retention

## Safe Update Process

1. **Local Development**
   - Set `FLASK_ENV=development`
   - Make and test changes locally
   - Run database migrations if needed

2. **Testing**
   - Test all changes thoroughly in development
   - Verify database migrations work correctly
   - Check all features with test data

3. **Deployment to Render**
   - Push changes to repository
   - Render automatically deploys from main branch
   - Database remains safe on persistent disk
   - No database initialization in production

## Environment Variables

### Development (.env)
```env
FLASK_ENV=development
SQLALCHEMY_DATABASE_URI=sqlite:///crm_multi.db
```

### Production (Render)
```env
FLASK_ENV=staging
SQLALCHEMY_DATABASE_URI=sqlite:////data/crm_multi.db
```

## Safety Measures
- Database initialization blocked in non-development environments
- Persistent disk mounted at `/data` in production
- Daily automated backups
- Clear logging of database operations
- Environment-specific configurations 