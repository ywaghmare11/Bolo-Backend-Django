from django.contrib import admin

from .models import Department, Tenant

# TenantMembership is not registered here -- Django admin cannot yet register
# a model with a composite primary key (see models.CompositePrimaryKey).


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "vertical", "created_at")
    search_fields = ("name",)
    list_filter = ("vertical",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "tenant", "head", "created_at")
    search_fields = ("name",)
    list_filter = ("tenant",)
